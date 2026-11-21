from __future__ import annotations

import argparse
from typing import Any

from src.graph import build_triage_graph

GOLDEN_CASES: list[dict[str, str]] = [
    {
        "name": "VAT rounding regression",
        "run_id": "run_101",
        "commit_sha": "a1b2c3",
        "expected_category": "product_regression",
        "expected_recommendation": "block_release",
    },
    {
        "name": "Webhook sandbox timeout",
        "run_id": "run_102",
        "commit_sha": "d4e5f6",
        "expected_category": "flaky_test",
        "expected_recommendation": "safe_to_proceed",
    },
    {
        "name": "Missing CI secret on new runner",
        "run_id": "run_103",
        "commit_sha": "g7h8i9",
        "expected_category": "environment_or_infra",
        "expected_recommendation": "hold_with_mitigation",
    },
]


def run_evals(use_llm: bool = False) -> dict[str, Any]:
    """Run all golden scenarios through the triage graph and compute accuracy metrics."""
    graph = build_triage_graph()
    results: list[dict[str, Any]] = []

    for idx, case in enumerate(GOLDEN_CASES, start=1):
        config = {"configurable": {"thread_id": f"eval-{idx}-{case['run_id']}"}}
        output = graph.invoke(
            {
                "run_id": case["run_id"],
                "commit_sha": case["commit_sha"],
                "use_llm": use_llm,
            },
            config=config,
        )
        report = output["triage_report"]

        cat_ok = report["root_cause_category"] == case["expected_category"]
        rec_ok = report["release_recommendation"] == case["expected_recommendation"]
        has_citations = len(report.get("citations", [])) > 0

        results.append(
            {
                "name": case["name"],
                "run_id": case["run_id"],
                "predicted_category": report["root_cause_category"],
                "expected_category": case["expected_category"],
                "predicted_recommendation": report["release_recommendation"],
                "expected_recommendation": case["expected_recommendation"],
                "category_match": cat_ok,
                "recommendation_match": rec_ok,
                "grounded": has_citations,
            }
        )

    total = len(results)
    metrics = {
        "mode": "ollama_llm" if use_llm else "deterministic_fallback",
        "total_cases": total,
        "category_accuracy": round(sum(r["category_match"] for r in results) / total, 2),
        "recommendation_accuracy": round(sum(r["recommendation_match"] for r in results) / total, 2),
        "citation_grounding_rate": round(sum(r["grounded"] for r in results) / total, 2),
        "details": results,
    }
    return metrics


def print_summary(metrics: dict[str, Any]) -> None:
    """Print a clean, readable benchmark report to the terminal."""
    print(f"\n=== AI Triage Pipeline Eval ({metrics['mode']}) ===")
    for item in metrics["details"]:
        status = "PASS" if (item["category_match"] and item["recommendation_match"]) else "FAIL"
        print(
            f"[{status}] {item['run_id']} ({item['name']}): "
            f"category={item['predicted_category']} | "
            f"gate={item['predicted_recommendation']} | "
            f"grounded={item['grounded']}"
        )

    print("\n--- Overall Metrics ---")
    print(f"Root Cause Accuracy     : {metrics['category_accuracy'] * 100:.0f}%")
    print(f"Release Gate Accuracy   : {metrics['recommendation_accuracy'] * 100:.0f}%")
    print(f"Citation Grounding Rate : {metrics['citation_grounding_rate'] * 100:.0f}%\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run AI Triage Pipeline evaluation benchmark.")
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Evaluate using local Ollama model instead of deterministic fallback.",
    )
    args = parser.parse_args()
    summary = run_evals(use_llm=args.use_llm)
    print_summary(summary)