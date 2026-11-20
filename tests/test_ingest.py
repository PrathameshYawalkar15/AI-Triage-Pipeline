from pathlib import Path
from src.ingest import load_git_diff, load_runbooks, parse_junit_xml


def test_parse_all_sample_runs():
    run_101 = parse_junit_xml(Path("data/sample_runs/run_101_junit.xml"), "run_101")
    run_102 = parse_junit_xml(Path("data/sample_runs/run_102_junit.xml"), "run_102")
    run_103 = parse_junit_xml(Path("data/sample_runs/run_103_junit.xml"), "run_103")

    assert len(run_101) == 1
    assert run_101[0].error_type == "AssertionError"

    assert len(run_102) == 1
    assert run_102[0].error_type == "ReadTimeout"

    assert len(run_103) == 2
    assert run_103[0].error_type == "KeyError"


def test_load_git_diff_and_runbooks():
    diff = load_git_diff(
        Path("data/git_diffs/commit_a1b2c3.patch"),
        commit_sha="a1b2c3",
        author="alex.dev@company.com",
        commit_message="refactor: simplify vat calculation",
    )
    assert diff.changed_files == ["src/billing/tax_calculator.py"]

    docs = load_runbooks(Path("data/runbooks"))
    assert len(docs) >= 6