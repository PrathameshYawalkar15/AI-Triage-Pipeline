from __future__ import annotations

import json
import os
from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from src import mcp_server
from src.retriever import RunbookRetriever
from src.schemas import (
    BugTicketDraft,
    EvidenceCitation,
    HumanReviewDecision,
    ReleaseRecommendation,
    RootCauseCategory,
    Severity,
    TriageReport,
)

DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")


class TriageState(TypedDict, total=False):
    # Inputs
    run_id: str
    commit_sha: str
    use_llm: bool

    # Context gathered from MCP resources/tools
    failures: list[dict[str, Any]]
    git_diff: dict[str, Any]
    test_history: dict[str, Any]

    # Agentic RAG state
    search_query: str
    retrieved_chunks: list[dict[str, Any]]
    retrieval_grade: dict[str, Any]
    retry_count: int

    # Diagnosis & ticket draft
    triage_report: dict[str, Any]
    ticket_draft: dict[str, Any]

    # Human-in-the-Loop review & final action
    human_decision: dict[str, Any]
    commit_result: dict[str, Any]


# ---------------------------------------------------------------------------
# GRAPH NODES
# ---------------------------------------------------------------------------


def gather_context(state: TriageState) -> TriageState:
    """Node 1: Fetch CI failures, Git diff, and test history via MCP functions."""
    run_id = state.get("run_id")
    commit_sha = state.get("commit_sha")
    if not run_id or not commit_sha:
        raise ValueError("run_id and commit_sha are required to gather context")

    failures = json.loads(mcp_server.get_ci_run_failures(run_id))
    git_diff = json.loads(mcp_server.get_git_diff(commit_sha))

    primary = failures[0] if isinstance(failures, list) and failures else {}
    test_id = primary.get("test_id", "")
    test_history = mcp_server.get_test_history(test_id) if test_id else {}

    # Build initial runbook search query from the error + changed files
    changed = " ".join(git_diff.get("changed_files", []))
    initial_query = (
        f"{primary.get('error_type', '')} "
        f"{primary.get('error_message', '')} "
        f"{primary.get('test_name', '')} {changed}"
    ).strip()

    return {
        "failures": failures if isinstance(failures, list) else [],
        "git_diff": git_diff,
        "test_history": test_history,
        "search_query": initial_query,
        "retry_count": 0,
    }


def retrieve_and_grade(state: TriageState) -> TriageState:
    """Node 2: Search runbooks and grade whether the retrieved evidence is strong enough."""
    retriever = RunbookRetriever(mcp_server.RUNBOOKS_DIR)
    query = state.get("search_query", "")
    chunks = retriever.retrieve(query, top_k=3)
    grade = retriever.grade_evidence(query, chunks)

    return {
        "retrieved_chunks": [c.model_dump() for c in chunks],
        "retrieval_grade": grade.model_dump(),
    }


def refine_query(state: TriageState) -> TriageState:
    """Node 2b (Retry): Narrow the search query to high-signal technical terms."""
    grade = state.get("retrieval_grade", {})
    refined = grade.get("refined_query") or state.get("search_query", "")
    return {
        "search_query": refined,
        "retry_count": state.get("retry_count", 0) + 1,
    }


def should_retry_retrieval(state: TriageState) -> str:
    """Conditional edge: retry retrieval once if evidence is weak."""
    grade = state.get("retrieval_grade", {})
    if not grade.get("is_sufficient", False) and state.get("retry_count", 0) < 1:
        return "refine_query"
    return "diagnose"


def _diagnose_deterministic(state: TriageState) -> TriageReport:
    """Fast, offline rule-based triage used when use_llm=False or Ollama is unavailable."""
    run_id = state["run_id"]
    commit_sha = state["commit_sha"]
    failures = state.get("failures", [])
    git_diff = state.get("git_diff", {})
    history = state.get("test_history", {})
    chunks = state.get("retrieved_chunks", [])

    primary = failures[0] if failures else {}
    error_type = primary.get("error_type", "")
    error_msg = primary.get("error_message", "")
    changed_files = git_diff.get("changed_files", [])
    flake_rate = history.get("flake_rate") or 0.0

    # Classify root cause using failure + diff + history signals
    if error_type == "KeyError" or any(".github/workflows" in f for f in changed_files):
        category = RootCauseCategory.ENVIRONMENT_OR_INFRA
        recommendation = ReleaseRecommendation.HOLD_WITH_MITIGATION
        component = changed_files[0] if changed_files else "ci_environment"
        summary = (
            f"CI environment/config drift detected ({error_type}: {error_msg}). "
            f"Changed files: {', '.join(changed_files) or 'none'}."
        )
        confidence = 0.92
    elif error_type == "ReadTimeout" and flake_rate >= 0.15:
        category = RootCauseCategory.FLAKY_TEST
        recommendation = ReleaseRecommendation.SAFE_TO_PROCEED
        component = primary.get("suite_or_file", "webhook_sandbox")
        summary = (
            f"Intermittent timeout ({error_type}) on a known flaky test "
            f"(historical flake rate: {int(flake_rate * 100)}%). "
            f"Git diff ({', '.join(changed_files) or 'none'}) is unrelated."
        )
        confidence = 0.88
    else:
        category = RootCauseCategory.PRODUCT_REGRESSION
        recommendation = ReleaseRecommendation.BLOCK_RELEASE
        component = changed_files[0] if changed_files else primary.get("suite_or_file", "unknown")
        summary = (
            f"Deterministic failure ({error_type}: {error_msg}) directly correlated "
            f"with code changes in {', '.join(changed_files) or 'unknown'}."
        )
        confidence = 0.95

    citations = [
        EvidenceCitation(
            source_type="ci_log",
            source_id=f"{run_id}::{primary.get('test_name', 'unknown')}",
            snippet=error_msg[:160],
            relevance_note="Primary failing test case from JUnit XML.",
        ),
        EvidenceCitation(
            source_type="git_diff",
            source_id=commit_sha,
            snippet=git_diff.get("commit_message", "")[:160],
            relevance_note=f"Touched files: {', '.join(changed_files) or 'none'}",
        ),
    ]
    for chunk in chunks[:2]:
        citations.append(
            EvidenceCitation(
                source_type="runbook",
                source_id=chunk["doc_id"],
                snippet=chunk["text"].splitlines()[0][:160],
                relevance_note=f"Matched terms: {', '.join(chunk.get('matched_terms', []))}",
            )
        )

    return TriageReport(
        run_id=run_id,
        commit_sha=commit_sha,
        root_cause_category=category,
        confidence=confidence,
        summary=summary,
        suspected_component=component,
        release_recommendation=recommendation,
        citations=citations,
    )


def _diagnose_with_ollama(state: TriageState) -> TriageReport:
    """Use local Ollama model with structured Pydantic output, falling back if unreachable."""
    from langchain_ollama import ChatOllama

    llm = ChatOllama(model=DEFAULT_OLLAMA_MODEL, temperature=0)
    structured_llm = llm.with_structured_output(TriageReport)

    prompt = (
        "You are a senior release triage engineer. Analyze the CI failure, Git diff, "
        "test history, and runbook excerpts below and return a grounded TriageReport.\n\n"
        f"Run ID: {state['run_id']}\n"
        f"Commit SHA: {state['commit_sha']}\n"
        f"Failures: {json.dumps(state.get('failures', []), indent=2)}\n"
        f"Git Diff: {json.dumps(state.get('git_diff', {}), indent=2)}\n"
        f"Test History: {json.dumps(state.get('test_history', {}), indent=2)}\n"
        f"Runbook Evidence: {json.dumps(state.get('retrieved_chunks', []), indent=2)}\n"
    )
    return structured_llm.invoke(prompt)


def diagnose(state: TriageState) -> TriageState:
    """Node 3: Produce a structured TriageReport and draft BugTicketDraft."""
    report: TriageReport
    if state.get("use_llm", False):
        try:
            report = _diagnose_with_ollama(state)
        except Exception:
            report = _diagnose_deterministic(state)
    else:
        report = _diagnose_deterministic(state)

    severity_map = {
        ReleaseRecommendation.BLOCK_RELEASE: Severity.HIGH,
        ReleaseRecommendation.HOLD_WITH_MITIGATION: Severity.MEDIUM,
        ReleaseRecommendation.SAFE_TO_PROCEED: Severity.LOW,
    }
    failures = state.get("failures", [])
    primary_test = failures[0].get("test_name", "unknown_test") if failures else "unknown_test"
    changed_files = state.get("git_diff", {}).get("changed_files", [])

    draft = BugTicketDraft(
        ticket_id=f"TRIAGE-{state['run_id'].upper()}",
        title=f"[{report.root_cause_category.value}] {primary_test} failed on {state['commit_sha']}",
        severity=severity_map[report.release_recommendation],
        root_cause_category=report.root_cause_category,
        description=report.summary,
        reproduction_steps=[
            f"git checkout {state['commit_sha']}",
            f"pytest -k {primary_test}",
        ],
        suspected_files=changed_files,
        citations=report.citations,
    )

    return {
        "triage_report": report.model_dump(mode="json"),
        "ticket_draft": draft.model_dump(mode="json"),
    }


def human_review(state: TriageState) -> TriageState:
    """
    Node 4 (HITL Gate): Pause execution using LangGraph interrupt() so a human
    can approve, reject, or override the draft ticket before any write occurs.
    """
    decision_payload = interrupt(
        {
            "message": "Review the triage report and draft bug ticket before committing.",
            "triage_report": state["triage_report"],
            "ticket_draft": state["ticket_draft"],
        }
    )

    decision = HumanReviewDecision(**decision_payload)
    updated_draft = dict(state["ticket_draft"])
    if decision.override_severity:
        updated_draft["severity"] = decision.override_severity.value
    if decision.override_category:
        updated_draft["root_cause_category"] = decision.override_category.value

    return {
        "human_decision": decision.model_dump(mode="json"),
        "ticket_draft": updated_draft,
    }


def commit_ticket(state: TriageState) -> TriageState:
    """Node 5: Commit the bug ticket via MCP tool ONLY if the human approved it."""
    decision = state.get("human_decision", {})
    if not decision.get("approved", False):
        return {
            "commit_result": {
                "status": "rejected_by_human",
                "reviewer_notes": decision.get("reviewer_notes", ""),
            }
        }

    draft = state["ticket_draft"]
    result = mcp_server.commit_bug_ticket(
        ticket_id=draft["ticket_id"],
        title=draft["title"],
        severity=draft["severity"],
        root_cause_category=draft["root_cause_category"],
        description=draft["description"],
        reproduction_steps=draft["reproduction_steps"],
        suspected_files=draft["suspected_files"],
        citations=draft["citations"],
        human_approved=True,
    )
    return {"commit_result": result}


# ---------------------------------------------------------------------------
# GRAPH BUILDER
# ---------------------------------------------------------------------------


def build_triage_graph(checkpointer: Any | None = None):
    """Compile and return the LangGraph triage workflow with HITL checkpointing."""
    builder = StateGraph(TriageState)

    builder.add_node("gather_context", gather_context)
    builder.add_node("retrieve_and_grade", retrieve_and_grade)
    builder.add_node("refine_query", refine_query)
    builder.add_node("diagnose", diagnose)
    builder.add_node("human_review", human_review)
    builder.add_node("commit_ticket", commit_ticket)

    builder.add_edge(START, "gather_context")
    builder.add_edge("gather_context", "retrieve_and_grade")
    builder.add_conditional_edges(
        "retrieve_and_grade",
        should_retry_retrieval,
        {
            "refine_query": "refine_query",
            "diagnose": "diagnose",
        },
    )
    builder.add_edge("refine_query", "retrieve_and_grade")
    builder.add_edge("diagnose", "human_review")
    builder.add_edge("human_review", "commit_ticket")
    builder.add_edge("commit_ticket", END)

    return builder.compile(checkpointer=checkpointer or MemorySaver())