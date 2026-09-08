"""
Huly Test Ingestion Service - Pydantic Data Models
"""

from enum import IntEnum
from typing import List, Optional
from pydantic import BaseModel, Field


class TestRunStatusEnum(IntEnum):
    UNTESTED = 0
    BLOCKED = 1
    PASSED = 2
    FAILED = 3


class TestCasePriorityEnum(IntEnum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    URGENT = 3


class TestCaseTypeEnum(IntEnum):
    FUNCTIONAL = 0
    PERFORMANCE = 1
    REGRESSION = 2
    SECURITY = 3
    SMOKE = 4
    USABILITY = 5


class IngestTestResultItem(BaseModel):
    name: str = Field(..., description="Test function or display name")
    suite_name: Optional[str] = Field(None, description="Module or parent test suite name")
    case_id: Optional[str] = Field(None, description="Existing Huly TestCase ID if explicitly mapped")
    status: TestRunStatusEnum = Field(..., description="Execution outcome (0: Untested, 1: Blocked, 2: Passed, 3: Failed)")
    duration_ms: Optional[float] = Field(None, description="Execution duration in milliseconds")
    error_message: Optional[str] = Field(None, description="Short failure summary or assertion error")
    error_trace: Optional[str] = Field(None, description="Full traceback, stdout, or execution log")


class CreateIngestRunRequest(BaseModel):
    project_id: str = Field(..., description="Target Huly TestProject Space ID (24-character hex)")
    run_name: str = Field(..., description="Name for the TestRun, e.g. 'Nightly CI #42'")
    run_id: Optional[str] = Field(None, description="Optional existing TestRun ID to append results to")
    auto_create_cases: bool = Field(True, description="Whether to auto-create missing TestSuites and TestCases")
    results: List[IngestTestResultItem] = Field(default_factory=list, description="List of test results")


class IngestRunResponse(BaseModel):
    success: bool
    run_id: str
    total_results: int
    passed: int
    failed: int
    blocked: int
    test_run_url: Optional[str] = None
