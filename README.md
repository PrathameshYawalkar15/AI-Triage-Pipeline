# AI Triage Pipeline

An **Agentic CI Failure Diagnostics, Runbook RAG & Human-in-the-Loop (HITL) Release Gate** copilot built with **Python 3.11, Pydantic v2, MCP (`MCPServer`), LangGraph, Ollama, and Streamlit**.

Instead of blindly auto-filing bug tickets from raw CI logs, this pipeline correlates failing tests with recent Git diffs, test history, and Markdown runbooks, grades its own retrieval quality, and **pauses at a LangGraph `interrupt()` gate** so an engineer can approve or reject every ticket before it is committed.

---

## Architecture

```text
CI JUnit XML + Git Diffs + Runbooks
               │
               ▼
      MCP Server (src/mcp_server.py)
   [Resources: ci://, git:// | Tools: search, history, commit]
               │
               ▼
    LangGraph Workflow (src/graph.py)
   ┌──────────────────────────────────────────────────────────┐
   │ 1. gather_context      → Fetch failure, diff, & history  │
   │ 2. retrieve_and_grade  → Search runbooks & grade match   │
   │    └─ (if weak) → refine_query → retry retrieval         │
   │ 3. diagnose            → Structured TriageReport (LLM /  │
   │                          deterministic fallback)         │
   │ 4. human_review        → LangGraph interrupt() HITL gate │
   │ 5. commit_ticket       → Write to store ONLY if approved │
   └──────────────────────────────────────────────────────────┘
               │
               ▼
   Streamlit Dashboard (src/app.py) & Evals (src/evals.py)
```

---

## Key Engineering Highlights

* **Strict Data Contracts (`src/schemas.py`):** Pydantic v2 models (`TestFailureEvent`, `GitDiffContext`, `TriageReport`, `BugTicketDraft`, `HumanReviewDecision`) enforce schema validation across ingestion, LLM output, and ticket persistence.
* **Model Context Protocol (`src/mcp_server.py`):** Exposes CI logs (`ci://runs/{run_id}/failures`) and Git diffs (`git://diffs/{commit_sha}`) as MCP resources, and runbook search, test history, and gated ticket creation as MCP tools.
* **Agentic RAG with Self-Grading (`src/retriever.py`):** Retrieves relevant Markdown runbook sections, grades evidence sufficiency (`grade_evidence`), and automatically refines the query for a retry if the initial match is weak.
* **Human-in-the-Loop Release Gate (`src/graph.py`):** Uses LangGraph `MemorySaver` + `interrupt()` to pause execution before any write action, resuming via `Command(resume=...)` only after human approval or rejection.
* **Local LLM + Deterministic Fallback:** Supports local Ollama (`qwen2.5-coder:7b`) with structured Pydantic output and automatically falls back to deterministic rule-based triage for fast, offline CI testing.
* **Automated Evals & Unit Tests (`src/evals.py`, `tests/`):** Benchmarks root-cause accuracy, release-gate accuracy, and citation grounding across golden scenarios, backed by 8 PyTest integration and unit tests.

---

## Sample Scenarios

| Run ID | Commit | Failure Signal | Expected Category | Release Gate |
| :--- | :--- | :--- | :--- | :--- |
| `run_101` | `a1b2c3` | `AssertionError` in `test_invoice_rounding_matches_ledger` | `product_regression` | `block_release` |
| `run_102` | `d4e5f6` | `ReadTimeout` on `test_webhook_delivery_retry` (docs-only diff) | `flaky_test` | `safe_to_proceed` |
| `run_103` | `g7h8i9` | `KeyError: 'STRIPE_SANDBOX_WEBHOOK_SECRET'` after runner change | `environment_or_infra` | `hold_with_mitigation` |

---

## Quickstart

### 1. Setup Environment
```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS / Linux:
# source .venv/bin/activate

pip install -e .
```

### 2. Run Unit & Workflow Tests
```bash
python -m pytest
```

### 3. Run Evaluation Benchmark
```bash
# Fast deterministic mode:
python -m src.evals

# With local Ollama (requires `ollama pull qwen2.5-coder:7b`):
python -m src.evals --use-llm
```

### 4. Launch Interactive Streamlit Dashboard
```bash
python -m streamlit run src/app.py
```

---

## Project Structure

```text
ai-triage-pipeline/
├── data/
│   ├── git_diffs/          # Sample unified git diff patches
│   ├── runbooks/           # Markdown operational runbooks
│   ├── sample_runs/        # PyTest JUnit XML failure reports
│   └── tickets_store.json  # Local persisted bug ticket store
├── src/
│   ├── app.py              # Streamlit HITL triage dashboard
│   ├── evals.py            # Golden-dataset evaluation benchmark
│   ├── graph.py            # LangGraph Agentic RAG + HITL workflow
│   ├── ingest.py           # JUnit XML, Robot XML, diff, & runbook parsers
│   ├── mcp_server.py       # MCPServer exposing resources & tools
│   ├── retriever.py        # Runbook keyword retriever & evidence grader
│   └── schemas.py          # Pydantic v2 data models
├── tests/
│   ├── test_graph.py       # End-to-end HITL approve/reject & scenario tests
│   ├── test_ingest.py      # Ingestion parser tests
│   └── test_mcp_server.py  # MCP resource & tool tests
├── pyproject.toml
└── README.md
```