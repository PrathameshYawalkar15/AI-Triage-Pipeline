from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field


class FrameworkType(str, Enum):
    PYTEST = "pytest"
    ROBOT = "robot"


class RootCauseCategory(str, Enum):
    PRODUCT_REGRESSION = "product_regression"
    FLAKY_TEST = "flaky_test"
    ENVIRONMENT_OR_INFRA = "environment_or_infra"
    TEST_OR_SPEC_DRIFT = "test_or_spec_drift"


class ReleaseRecommendation(str, Enum):
    BLOCK_RELEASE = "block_release"
    HOLD_WITH_MITIGATION = "hold_with_mitigation"
    SAFE_TO_PROCEED = "safe_to_proceed"


class Severity(str, Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class TestFailureEvent(BaseModel):
    run_id: str
    framework: FrameworkType
    test_id: str
    test_name: str
    suite_or_file: str
    duration_sec: float = Field(ge=0.0)
    error_type: str
    error_message: str
    stack_trace: str
    log_excerpt: str = ""
    tags: list[str] = Field(default_factory=list)


class GitDiffContext(BaseModel):
    commit_sha: str
    author: str
    commit_message: str
    changed_files: list[str] = Field(default_factory=list)
    diff_patch: str


class EvidenceCitation(BaseModel):
    source_type: Literal["ci_log", "git_diff", "runbook", "test_history"]
    source_id: str
    snippet: str
    relevance_note: str


class TriageReport(BaseModel):
    run_id: str
    commit_sha: str
    root_cause_category: RootCauseCategory
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str
    suspected_component: str
    release_recommendation: ReleaseRecommendation
    citations: list[EvidenceCitation] = Field(default_factory=list)
    needs_more_evidence: bool = False
    follow_up_query: str | None = None


class BugTicketDraft(BaseModel):
    ticket_id: str
    title: str
    severity: Severity
    root_cause_category: RootCauseCategory
    description: str
    reproduction_steps: list[str] = Field(default_factory=list)
    suspected_files: list[str] = Field(default_factory=list)
    citations: list[EvidenceCitation] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class HumanReviewDecision(BaseModel):
    approved: bool
    reviewer_notes: str = ""
    override_severity: Severity | None = None
    override_category: RootCauseCategory | None = None
    override_recommendation: ReleaseRecommendation | None = None