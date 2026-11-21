import json
from langgraph.types import Command

from src import mcp_server
from src.graph import build_triage_graph


def test_graph_approve_commits_ticket(tmp_path, monkeypatch):
    """Full HITL approval flow: pause at interrupt, resume with approval, verify JSON write."""
    store_file = tmp_path / "tickets.json"
    monkeypatch.setattr(mcp_server, "TICKETS_STORE_PATH", store_file)

    graph = build_triage_graph()
    config = {"configurable": {"thread_id": "test-approve-101"}}

    # 1. Run until the Human-in-the-Loop interrupt
    paused = graph.invoke(
        {"run_id": "run_101", "commit_sha": "a1b2c3", "use_llm": False},
        config=config,
    )
    assert "__interrupt__" in paused
    assert paused["triage_report"]["root_cause_category"] == "product_regression"
    assert paused["triage_report"]["release_recommendation"] == "block_release"

    # 2. Resume with human approval
    final = graph.invoke(
        Command(resume={"approved": True, "reviewer_notes": "Confirmed VAT rounding regression."}),
        config=config,
    )
    assert final["commit_result"]["status"] == "committed"

    # 3. Verify ticket was persisted to the store
    saved = json.loads(store_file.read_text(encoding="utf-8"))
    assert len(saved["tickets"]) == 1
    assert saved["tickets"][0]["ticket_id"] == "TRIAGE-RUN_101"


def test_graph_reject_blocks_ticket_write(tmp_path, monkeypatch):
    """Full HITL rejection flow: pause at interrupt, resume with rejection, verify no write."""
    store_file = tmp_path / "tickets.json"
    monkeypatch.setattr(mcp_server, "TICKETS_STORE_PATH", store_file)

    graph = build_triage_graph()
    config = {"configurable": {"thread_id": "test-reject-102"}}

    paused = graph.invoke(
        {"run_id": "run_102", "commit_sha": "d4e5f6", "use_llm": False},
        config=config,
    )
    assert "__interrupt__" in paused
    assert paused["triage_report"]["root_cause_category"] == "flaky_test"
    assert paused["triage_report"]["release_recommendation"] == "safe_to_proceed"

    final = graph.invoke(
        Command(resume={"approved": False, "reviewer_notes": "Known sandbox flake, no ticket needed."}),
        config=config,
    )
    assert final["commit_result"]["status"] == "rejected_by_human"
    assert not store_file.exists()


def test_graph_classifies_env_drift():
    """Verify run_103 (missing CI secret) is classified as environment_or_infra."""
    graph = build_triage_graph()
    config = {"configurable": {"thread_id": "test-env-103"}}

    paused = graph.invoke(
        {"run_id": "run_103", "commit_sha": "g7h8i9", "use_llm": False},
        config=config,
    )
    assert "__interrupt__" in paused
    assert paused["triage_report"]["root_cause_category"] == "environment_or_infra"
    assert paused["triage_report"]["release_recommendation"] == "hold_with_mitigation"