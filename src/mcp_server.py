from __future__ import annotations

import json
import os
import re
from importlib import import_module
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from src.ingest import load_git_diff, load_runbooks, parse_junit_xml
from src.schemas import BugTicketDraft, EvidenceCitation, RootCauseCategory, Severity

# Base paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RUNS_DIR = DATA_DIR / "sample_runs"
DIFFS_DIR = DATA_DIR / "git_diffs"
RUNBOOKS_DIR = DATA_DIR / "runbooks"
TICKETS_STORE_PATH = Path(
    os.getenv("TICKETS_STORE_PATH", str(DATA_DIR / "tickets_store.json"))
)

# Metadata mapping for sample commits
COMMIT_METADATA: dict[str, dict[str, str]] = {
    "a1b2c3": {
        "file": "commit_a1b2c3.patch",
        "author": "alex.dev@company.com",
        "message": "refactor: simplify vat calculation in tax_calculator.py",
    },
    "d4e5f6": {
        "file": "commit_d4e5f6.patch",
        "author": "sara.docs@company.com",
        "message": "docs: add ruff lint step to README",
    },
    "g7h8i9": {
        "file": "commit_g7h8i9.patch",
        "author": "ops.bot@company.com",
        "message": "ci: migrate integration-tests to ubuntu-24.04-ephemeral",
    },
}

# Simulated historical pass/fail telemetry for flake detection
TEST_HISTORY_DB: dict[str, dict[str, Any]] = {
    "billing_service.tests.test_invoices::test_invoice_rounding_matches_ledger": {
        "last_20_runs_passed": 20,
        "last_20_runs_failed": 0,
        "flake_rate": 0.0,
        "notes": "Historically 100% deterministic. Failure strongly indicates a real code regression.",
    },
    "billing_service.tests.test_webhooks::test_webhook_delivery_retry": {
        "last_20_runs_passed": 16,
        "last_20_runs_failed": 4,
        "flake_rate": 0.20,
        "notes": "Known intermittent ReadTimeout against sandbox-webhook.internal:8080.",
    },
    "billing_service.tests.test_stripe_sync::test_sync_customer_payment_method": {
        "last_20_runs_passed": 20,
        "last_20_runs_failed": 0,
        "flake_rate": 0.0,
        "notes": "Fails only when STRIPE_SANDBOX_WEBHOOK_SECRET is missing from runner env.",
    },
}

mcp = MCPServer("AI-Triage-Pipeline")


# ---------------------------------------------------------------------------
# MCP RESOURCES (Read-Only Context)
# ---------------------------------------------------------------------------


@mcp.resource("ci://runs/{run_id}/failures")
def get_ci_run_failures(run_id: str) -> str:
    """Return parsed TestFailureEvent records for a given CI run ID."""
    xml_path = RUNS_DIR / f"{run_id}_junit.xml"
    if not xml_path.exists():
        return json.dumps({"error": f"Run '{run_id}' not found at {xml_path.name}"})

    failures = parse_junit_xml(xml_path, run_id=run_id)
    return json.dumps([f.model_dump(mode="json") for f in failures], indent=2)


@mcp.resource("git://diffs/{commit_sha}")
def get_git_diff(commit_sha: str) -> str:
    """Return structured GitDiffContext for a given commit SHA."""
    meta = COMMIT_METADATA.get(commit_sha)
    if not meta:
        return json.dumps({"error": f"Commit '{commit_sha}' not found in metadata."})

    diff_path = DIFFS_DIR / meta["file"]
    if not diff_path.exists():
        return json.dumps({"error": f"Diff file '{diff_path.name}' not found."})

    diff_ctx = load_git_diff(
        diff_path=diff_path,
        commit_sha=commit_sha,
        author=meta["author"],
        commit_message=meta["message"],
    )
    return diff_ctx.model_dump_json(indent=2)


# ---------------------------------------------------------------------------
# MCP TOOLS (Agent Actions)
# ---------------------------------------------------------------------------


@mcp.tool()
def search_runbooks(query: str, top_k: int = 3) -> list[dict[str, Any]]:
    """
    Search incident runbooks by keyword relevance.
    Returns ranked Markdown chunks with doc_id, source filename, score, and text.
    """
    docs = load_runbooks(RUNBOOKS_DIR)
    query_tokens = set(re.findall(r"[a-zA-Z0-9_]+", query.lower()))
    if not query_tokens:
        return []

    scored: list[dict[str, Any]] = []
    for doc in docs:
        doc_tokens = set(re.findall(r"[a-zA-Z0-9_]+", doc["text"].lower()))
        overlap = query_tokens.intersection(doc_tokens)
        if not overlap:
            continue
        score = round(len(overlap) / len(query_tokens), 3)
        scored.append(
            {
                "doc_id": doc["doc_id"],
                "source": doc["source"],
                "score": score,
                "matched_terms": sorted(overlap),
                "text": doc["text"],
            }
        )

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


@mcp.tool()
def get_test_history(test_id: str) -> dict[str, Any]:
    """
    Look up historical pass/fail and flake rate for a specific test_id
    (e.g., 'billing_service.tests.test_webhooks::test_webhook_delivery_retry').
    """
    if test_id in TEST_HISTORY_DB:
        return {"test_id": test_id, **TEST_HISTORY_DB[test_id]}
    return {
        "test_id": test_id,
        "last_20_runs_passed": None,
        "last_20_runs_failed": None,
        "flake_rate": None,
        "notes": "No historical telemetry found for this test.",
    }


@mcp.tool()
def commit_bug_ticket(
    ticket_id: str,
    title: str,
    severity: str,
    root_cause_category: str,
    description: str,
    reproduction_steps: list[str],
    suspected_files: list[str],
    citations: list[dict[str, str]],
    human_approved: bool = False,
) -> dict[str, Any]:
    """
    Persist a validated BugTicketDraft to the local ticket store.
    GATED WRITE ACTION: Requires human_approved=True to prevent autonomous ticket spam.
    """
    if not human_approved:
        return {
            "status": "blocked",
            "reason": "Human-in-the-Loop approval is required (human_approved=True) before committing a ticket.",
        }

    # Validate payload strictly via Pydantic v2
    draft = BugTicketDraft(
        ticket_id=ticket_id,
        title=title,
        severity=Severity(severity),
        root_cause_category=RootCauseCategory(root_cause_category),
        description=description,
        reproduction_steps=reproduction_steps,
        suspected_files=suspected_files,
        citations=[EvidenceCitation(**c) for c in citations],
    )

    if TICKETS_STORE_PATH.exists() and TICKETS_STORE_PATH.read_text(encoding="utf-8").strip():
        store = json.loads(TICKETS_STORE_PATH.read_text(encoding="utf-8"))
    else:
        store = {"tickets": []}

    store["tickets"].append(draft.model_dump(mode="json"))
    TICKETS_STORE_PATH.write_text(json.dumps(store, indent=2), encoding="utf-8")

    return {
        "status": "committed",
        "ticket_id": draft.ticket_id,
        "store_path": str(TICKETS_STORE_PATH),
    }


if __name__ == "__main__":
    mcp.run()