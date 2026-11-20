import json
from src import mcp_server


def test_mcp_resources():
    failures_json = mcp_server.get_ci_run_failures("run_101")
    failures = json.loads(failures_json)
    assert len(failures) == 1
    assert failures[0]["test_name"] == "test_invoice_rounding_matches_ledger"

    diff_json = mcp_server.get_git_diff("a1b2c3")
    diff = json.loads(diff_json)
    assert diff["changed_files"] == ["src/billing/tax_calculator.py"]


def test_search_runbooks_and_history():
    results = mcp_server.search_runbooks("ReadTimeout sandbox-webhook")
    assert len(results) >= 1
    assert results[0]["source"] == "webhook_retries_and_timeouts.md"

    hist = mcp_server.get_test_history(
        "billing_service.tests.test_webhooks::test_webhook_delivery_retry"
    )
    assert hist["flake_rate"] == 0.20


def test_commit_ticket_blocks_without_approval(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "TICKETS_STORE_PATH", tmp_path / "tickets.json")

    blocked = mcp_server.commit_bug_ticket(
        ticket_id="TRIAGE-101",
        title="VAT rounding regression",
        severity="High",
        root_cause_category="product_regression",
        description="Line-item rounding removed.",
        reproduction_steps=["pytest tests/test_invoices.py"],
        suspected_files=["src/billing/tax_calculator.py"],
        citations=[
            {
                "source_type": "runbook",
                "source_id": "vat_rounding_policy#sec_1",
                "snippet": "Rule INV-TAX-02",
                "relevance_note": "Violates per-line rounding invariant.",
            }
        ],
        human_approved=False,
    )
    assert blocked["status"] == "blocked"