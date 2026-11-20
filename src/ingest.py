from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from src.schemas import FrameworkType, GitDiffContext, TestFailureEvent


def parse_junit_xml(xml_path: Path, run_id: str) -> list[TestFailureEvent]:
    """Extract failed and errored test cases from a PyTest JUnit XML report."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    failures: list[TestFailureEvent] = []

    for case in root.iter("testcase"):
        failure_node = case.find("failure")
        error_node = case.find("error")
        issue_node = failure_node if failure_node is not None else error_node
        if issue_node is None:
            continue

        raw_trace = (issue_node.text or "").strip()
        lines = raw_trace.splitlines()
        excerpt = "\n".join(lines[-8:]) if lines else issue_node.attrib.get("message", "")

        failures.append(
            TestFailureEvent(
                run_id=run_id,
                framework=FrameworkType.PYTEST,
                test_id=f"{case.attrib.get('classname', 'unknown')}::{case.attrib.get('name', 'unknown')}",
                test_name=case.attrib.get("name", "unknown"),
                suite_or_file=case.attrib.get("classname", str(xml_path)),
                duration_sec=float(case.attrib.get("time", "0.0") or 0.0),
                error_type=issue_node.attrib.get("type", "AssertionError"),
                error_message=issue_node.attrib.get("message", lines[-1] if lines else ""),
                stack_trace=raw_trace,
                log_excerpt=excerpt,
            )
        )

    return failures


def parse_robot_output_xml(xml_path: Path, run_id: str) -> list[TestFailureEvent]:
    """Extract failed tests from a Robot Framework output.xml file."""
    try:
        from robot.api import ExecutionResult  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Install `robotframework` to parse Robot output.xml files.") from exc

    result = ExecutionResult(str(xml_path))
    failures: list[TestFailureEvent] = []

    for test in result.suite.tests:
        if test.passed:
            continue
        failures.append(
            TestFailureEvent(
                run_id=run_id,
                framework=FrameworkType.ROBOT,
                test_id=test.id,
                test_name=test.name,
                suite_or_file=test.parent.longname if test.parent else str(xml_path),
                duration_sec=round(test.elapsed_time / 1000.0, 3),
                error_type="RobotAssertionFailure",
                error_message=test.message,
                stack_trace=test.message,
                log_excerpt=test.message,
                tags=list(test.tags),
            )
        )

    return failures


def load_git_diff(
    diff_path: Path, commit_sha: str, author: str, commit_message: str
) -> GitDiffContext:
    """Load a unified git diff patch and extract touched file paths."""
    patch_text = diff_path.read_text(encoding="utf-8")
    changed_files: list[str] = []
    for line in patch_text.splitlines():
        if line.startswith("+++ b/"):
            file_path = line.removeprefix("+++ b/").strip()
            if file_path and file_path not in changed_files:
                changed_files.append(file_path)

    return GitDiffContext(
        commit_sha=commit_sha,
        author=author,
        commit_message=commit_message,
        changed_files=changed_files,
        diff_patch=patch_text,
    )


def load_runbooks(runbooks_dir: Path) -> list[dict[str, str]]:
    """Load Markdown runbooks as structured chunks with source identifiers."""
    docs: list[dict[str, str]] = []
    for md_file in sorted(runbooks_dir.glob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        sections = content.split("\n## ")
        for idx, section in enumerate(sections):
            chunk_text = section if idx == 0 else f"## {section}"
            docs.append(
                {
                    "doc_id": f"{md_file.stem}#sec_{idx}",
                    "source": md_file.name,
                    "text": chunk_text.strip(),
                }
            )
    return docs