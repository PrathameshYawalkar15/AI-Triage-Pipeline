from __future__ import annotations

import json
import uuid
import streamlit as st
from langgraph.types import Command

from src import mcp_server
from src.graph import build_triage_graph

SCENARIOS = {
    "run_101 — VAT Rounding Regression (a1b2c3)": ("run_101", "a1b2c3"),
    "run_102 — Webhook Sandbox Timeout (d4e5f6)": ("run_102", "d4e5f6"),
    "run_103 — Missing CI Secret / Env Drift (g7h8i9)": ("run_103", "g7h8i9"),
}

st.set_page_config(page_title="AI Triage Pipeline", layout="wide")
st.title("AI Triage Pipeline")
st.caption("Agentic CI Failure Diagnostics, Runbook RAG & Human-in-the-Loop Release Gate")

# Keep a single compiled graph (and its MemorySaver checkpointer) across reruns
if "graph" not in st.session_state:
    st.session_state.graph = build_triage_graph()
if "thread_id" not in st.session_state:
    st.session_state.thread_id = None
if "paused_state" not in st.session_state:
    st.session_state.paused_state = None
if "final_state" not in st.session_state:
    st.session_state.final_state = None

# ---------------------------------------------------------------------------
# SIDEBAR CONTROLS
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("1. Select CI Failure")
    selected_label = st.selectbox("Sample Scenario", list(SCENARIOS.keys()))
    run_id, commit_sha = SCENARIOS[selected_label]

    use_llm = st.checkbox("Use local Ollama LLM", value=False)
    if st.button("Run Triage", type="primary", use_container_width=True):
        thread_id = f"ui-{uuid.uuid4().hex[:8]}"
        config = {"configurable": {"thread_id": thread_id}}

        with st.spinner("Gathering CI logs, Git diff, and runbooks..."):
            paused = st.session_state.graph.invoke(
                {"run_id": run_id, "commit_sha": commit_sha, "use_llm": use_llm},
                config=config,
            )

        st.session_state.thread_id = thread_id
        st.session_state.paused_state = paused
        st.session_state.final_state = None

# ---------------------------------------------------------------------------
# MAIN TRIAGE VIEW
# ---------------------------------------------------------------------------
paused = st.session_state.paused_state
final = st.session_state.final_state

if paused is None:
    st.info("Select a CI failure scenario in the sidebar and click **Run Triage** to begin.")
else:
    report = paused["triage_report"]
    draft = paused["ticket_draft"]

    st.subheader("2. Triage Report")
    col1, col2, col3 = st.columns(3)
    col1.metric("Root Cause", report["root_cause_category"])
    col2.metric("Release Gate", report["release_recommendation"])
    col3.metric("Confidence", f"{int(report['confidence'] * 100)}%")

    st.write(f"**Summary:** {report['summary']}")
    st.write(f"**Suspected Component:** `{report['suspected_component']}`")

    with st.expander("Evidence Citations", expanded=True):
        for cite in report.get("citations", []):
            st.markdown(
                f"- **[{cite['source_type']}]** `{cite['source_id']}` — "
                f"{cite['snippet']} *(Note: {cite['relevance_note']})*"
            )

    st.subheader("3. Draft Bug Ticket (Paused at Human-in-the-Loop Gate)")
    st.json(draft)

    if final is None:
        notes = st.text_input(
            "Reviewer Notes",
            placeholder="e.g., Confirmed regression, blocking release until fixed.",
        )
        btn_col1, btn_col2 = st.columns(2)

        if btn_col1.button("Approve & Commit Ticket", type="primary", use_container_width=True):
            config = {"configurable": {"thread_id": st.session_state.thread_id}}
            st.session_state.final_state = st.session_state.graph.invoke(
                Command(resume={"approved": True, "reviewer_notes": notes}),
                config=config,
            )
            st.rerun()

        if btn_col2.button("Reject Ticket", use_container_width=True):
            config = {"configurable": {"thread_id": st.session_state.thread_id}}
            st.session_state.final_state = st.session_state.graph.invoke(
                Command(resume={"approved": False, "reviewer_notes": notes}),
                config=config,
            )
            st.rerun()
    else:
        result = final.get("commit_result", {})
        if result.get("status") == "committed":
            st.success(f"Ticket committed to `{mcp_server.TICKETS_STORE_PATH}`.")
        else:
            st.warning(f"Ticket rejected by human reviewer. Notes: {result.get('reviewer_notes', '')}")

# ---------------------------------------------------------------------------
# COMMITTED TICKETS STORE
# ---------------------------------------------------------------------------
st.divider()
st.subheader("Committed Tickets Store (`data/tickets_store.json`)")
if mcp_server.TICKETS_STORE_PATH.exists():
    store_data = json.loads(mcp_server.TICKETS_STORE_PATH.read_text(encoding="utf-8-sig"))
    tickets = store_data.get("tickets", [])
    if tickets:
        st.json(tickets)
    else:
        st.caption("No tickets committed yet.")
else:
    st.caption("Ticket store file not created yet.")