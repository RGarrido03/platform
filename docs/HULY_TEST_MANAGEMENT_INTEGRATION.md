# Huly Test Management: External API & Pytest Ingestion Architecture

**Technical Specification & Implementation Guide**  
**Role**: Test Management & Integration Specialist (`test_integration_engineer`)  
**Task**: `t5` — Research external API & Python Pytest ingestion for test management  
**Date**: May 2024 / Huly v0.7+  

---

## Executive Summary

Huly features a native Test Management subsystem (`models/test-management`, `plugins/test-management*`) that models test projects, hierarchical test suites, test cases, execution plans, and test runs. However, Huly currently lacks an automated ingestion path for external CI/CD test frameworks.

This document specifies:
1. **The Huly Test Management Domain Model**: Object hierarchy, collection attachments, status enums, and storage mechanics in CockroachDB.
2. **The Transactor Mutation Engine**: How external clients authenticate via API Tokens (Personal Access Tokens) and execute atomic mutations using `TxCreateDoc`, `TxUpdateDoc`, and batch `TxApplyIf` over HTTP REST RPC (`POST /api/v1/tx/:workspaceId`).
3. **The Standalone Ingestion Service (`huly-test-ingest`)**: A high-performance REST microservice (FastAPI / Node.js) that accepts industry-standard test reports (JUnit XML, Pytest JSON, Allure, Cucumber) and reconciles them into Huly entities.
4. **The `pytest-huly` Python Package**: A native Pytest plugin that intercepts test execution hooks (`pytest_runtest_makereport`, `pytest_sessionfinish`), synchronizes test suites/cases, and publishes test runs directly to Huly.

---

## 1. Huly Test Management Domain Model

Huly's test management architecture is defined in `models/test-management/src/types.ts` and `plugins/test-management/src/types.ts`. All entities operate within the storage domain `DOMAIN_TEST_MANAGEMENT = 'test-management'`.

### 1.1 Entity Relationship Diagram

```
+-------------------------------------------------------------+
|               TestProject (TypedSpace / Doc)                |
|           _class: testManagement:class:TestProject          |
|              _id: <24-hex>, name, fullDescription           |
+-------------------------------------------------------------+
       |                                   |
       | contains                          | contains
       v                                   v
+-----------------------------+     +-----------------------------+
|      TestSuite (Doc)        |     |        TestPlan (Doc)       |
|  _class: ...:TestSuite      |     |    _class: ...:TestPlan     |
|  parent: Ref<TestSuite>     |     |    items: Collection        |
|  testCases: Collection      |     +-----------------------------+
+-----------------------------+                    |
       |                                           | contains
       | contains ('testCases')                    v
       v                                    +---------------------+
+-----------------------------+             |  TestPlanItem (Doc) |
|      TestCase (Doc)         |<------------+  attachedTo: Plan   |
|  _class: ...:TestCase       |  references |  testCase: TestCase |
|  attachedTo: TestSuite      |             +---------------------+
|  type: TestCaseType         |
|  priority: TestCasePriority |
|  status: TestCaseStatus     |
+-----------------------------+
       ^
       | referenced by
       |
+-----------------------------+             +---------------------+
|       TestRun (Doc)         | contains    |  TestResult (Doc)   |
|   _class: ...:TestRun       |------------>| attachedTo: TestRun |
|   dueDate: Timestamp        | ('results') | testCase: TestCase  |
|   results: Collection       |             | status: RunStatus   |
+-----------------------------+             +---------------------+
```

### 1.2 Entity Specifications

#### 1.2.1 `TestProject`
- **Base Class**: `core.class.TypedSpace`
- **Class Identifier**: `testManagement:class:TestProject`
- **Storage**: CockroachDB `space` / `default` domain tables partitioned by `("workspaceId", _id)`.
- **Purpose**: Workspace container partitioned for test suites, runs, and plans.
- **Attributes**:
  - `name`: `string`
  - `fullDescription`: `Markup` (collaborative rich text or markdown string)
  - `descriptor`: `testManagement:descriptors:ProjectType`

#### 1.2.2 `TestSuite`
- **Base Class**: `core.class.Doc`
- **Class Identifier**: `testManagement:class:TestSuite`
- **Attributes**:
  - `_id`: `Ref<TestSuite>` (24-character hexadecimal ID)
  - `space`: `Ref<TestProject>`
  - `name`: `string` (e.g. `"Authentication & Session"`)
  - `description`: `string | null`
  - `parent`: `Ref<TestSuite>` — Self-referential hierarchy. Top-level suites set `parent = "testManagement:ids:NoParent"`.
  - `testCases`: `CollectionSize<TestCase>` (embedded counter of attached test cases)

#### 1.2.3 `TestCase` (Attached Document)
- **Base Class**: `core.class.AttachedDoc`
- **Class Identifier**: `testManagement:class:TestCase`
- **Attachment Specification**:
  - `attachedTo`: `Ref<TestSuite>` (Parent suite ID)
  - `attachedToClass`: `testManagement:class:TestSuite`
  - `collection`: `'testCases'`
  - `space`: `Ref<TestProject>`
- **Attributes**:
  - `name`: `string` (Title of the test case, e.g. `"Verify OTP login with valid credentials"`)
  - `description`: `MarkupBlobRef | null` (Rich-text description, preconditions, steps)
  - `type`: `TestCaseType` (numeric enum):
    - `0`: `Functional`
    - `1`: `Performance`
    - `2`: `Regression`
    - `3`: `Security`
    - `4`: `Smoke`
    - `5`: `Usability`
  - `priority`: `TestCasePriority` (numeric enum):
    - `0`: `Low`
    - `1`: `Medium`
    - `2`: `High`
    - `3`: `Urgent`
  - `status`: `TestCaseStatus` (numeric enum):
    - `0`: `Draft`
    - `1`: `ReadyForReview`
    - `2`: `FixReviewComments`
    - `3`: `Approved`
    - `4`: `Rejected`
  - `assignee`: `Ref<Employee> | null`
  - `attachments`: `CollectionSize<Attachment>`
  - `comments`: `number`

#### 1.2.4 `TestRun`
- **Base Class**: `core.class.Doc`
- **Class Identifier**: `testManagement:class:TestRun`
- **Attributes**:
  - `_id`: `Ref<TestRun>` (24-character hexadecimal ID)
  - `space`: `Ref<TestProject>`
  - `name`: `string` (e.g. `"Nightly Regression #482 - commit 9f12ab"`)
  - `description`: `MarkupBlobRef | null`
  - `dueDate`: `Timestamp | undefined` (Unix timestamp in milliseconds)
  - `results`: `CollectionSize<TestResult>` (counter of attached test results)

#### 1.2.5 `TestResult` (Attached Document)
- **Base Class**: `core.class.AttachedDoc`
- **Class Identifier**: `testManagement:class:TestResult`
- **Attachment Specification**:
  - `attachedTo`: `Ref<TestRun>` (Parent run ID)
  - `attachedToClass`: `testManagement:class:TestRun`
  - `collection`: `'results'`
  - `space`: `Ref<TestProject>`
- **Attributes**:
  - `name`: `string` (Test name or function title)
  - `testCase`: `Ref<TestCase>` (Foreign reference to TestCase definition)
  - `testSuite`: `Ref<TestSuite>` (Foreign reference to parent suite)
  - `status`: `TestRunStatus` (numeric enum):
    - `0`: `Untested` (default initial state)
    - `1`: `Blocked` (skipped / pending / blocked)
    - `2`: `Passed` (successful test execution)
    - `3`: `Failed` (assertion error / exception)
  - `description`: `MarkupBlobRef | null` (Execution failure stack trace, stdout/stderr, or logs)
  - `assignee`: `Ref<Employee> | null`
  - `attachments`: `CollectionSize<Attachment>` (screenshots, trace recordings)
  - `comments`: `number`

---

## 2. Authentication & Transactor Mutation Flow

### 2.1 Authentication Mechanism: API Tokens

External CI/CD scripts and microservices authenticate using **API Tokens (Personal Access Tokens)**.

1. **Token Generation**:
   - Created in Huly Web UI (`Settings` -> `API Tokens`) or via Account Service API:
     `POST /api/v1/account/create-api-token` with `{ name: "CI Ingest", workspaceUuid: "<uuid>", expiryDays: 90 }`.
2. **Token Format**:
   - The token is a signed JSON Web Token (JWT) signed by `SERVER_SECRET`:
     ```json
     {
       "account": "e6a25697-717e-4054-9461-8ffebc43f773",
       "workspace": "4722513f-801e-4581-9b62-677f59d58434",
       "extra": {
         "apiTokenId": "87c53d17-915d-4f11-8ec2-1323bdfec881"
       },
       "exp": 1755294000
     }
     ```
3. **Revocation & Validation**:
   - When the Transactor receives a request, `withSession` parses `Authorization: Bearer <token>`.
   - If `extra.apiTokenId` is present, `apiTokenRevocationChecker` validates the token against Account Service (`REVOCATION_CACHE_TTL_MS = 60,000`).
4. **Header Convention**:
   ```http
   Authorization: Bearer <huly_api_token>
   Content-Type: application/json
   ```

---

### 2.2 Transactor REST RPC Endpoints (`pods/server/src/rpc.ts`)

The Transactor runs on port `3332` (or via reverse proxy on `/api/v1/*`):

| Endpoint | Method | Request Payload | Response |
|---|---|---|---|
| `/api/v1/ping/:workspaceId` | `GET` | *(none)* | `{ pong: true, lastTx: 1042 }` |
| `/api/v1/account/:workspaceId` | `GET` | *(none)* | Account info, user UUID, social IDs |
| `/api/v1/generate-id/:workspaceId` | `GET` | *(none)* | `{ id: "673abc123456789012345678" }` |
| `/api/v1/find-all/:workspaceId` | `POST` | `{ "_class": "...", "query": {...} }` | Array of matching documents |
| `/api/v1/tx/:workspaceId` | `POST` | `TxCreateDoc` \| `TxUpdateDoc` \| `TxApplyIf` | `{ result: "ok" }` |

---

### 2.3 ID Generation

All Huly object IDs are 24-character hexadecimal strings (`^[0-9a-f]{24}$`).
An external client can call `/api/v1/generate-id/:workspaceId`, or generate them locally with 0 latency:

```python
import time
import secrets

def generate_huly_id() -> str:
    """Generate a 24-character hex ID matching Huly's generateId() algorithm."""
    timestamp_hex = f"{int(time.time()):08x}"   # 8 hex chars (4 bytes timestamp)
    random_hex = secrets.token_hex(5)           # 10 hex chars (5 bytes random)
    counter_hex = secrets.token_hex(3)          # 6 hex chars (3 bytes counter)
    return f"{timestamp_hex}{random_hex}{counter_hex}"
```

---

### 2.4 Transaction Shapes

#### 2.4.1 Creating a `TestRun` (`TxCreateDoc`)
```json
{
  "_id": "673abc000000000000000001",
  "_class": "core:class:TxCreateDoc",
  "objectId": "673abc111111111111111111",
  "objectClass": "testManagement:class:TestRun",
  "objectSpace": "673abc999999999999999999",
  "attributes": {
    "name": "Pytest CI Run #120 - commit 8a3f4e",
    "description": null,
    "dueDate": 1747584000000
  }
}
```

#### 2.4.2 Creating a `TestResult` attached to `TestRun` (`TxCreateDoc` with Collection)
```json
{
  "_id": "673abc000000000000000002",
  "_class": "core:class:TxCreateDoc",
  "objectId": "673abc222222222222222222",
  "objectClass": "testManagement:class:TestResult",
  "objectSpace": "673abc999999999999999999",
  "attachedTo": "673abc111111111111111111",
  "attachedToClass": "testManagement:class:TestRun",
  "collection": "results",
  "attributes": {
    "name": "tests/test_auth.py::test_login_success",
    "testCase": "673abc333333333333333333",
    "testSuite": "673abc444444444444444444",
    "status": 2,
    "description": null
  }
}
```

#### 2.4.3 Atomic Batch Ingestion via `TxApplyIf`
To avoid hundreds of network roundtrips, the entire test run and all test results can be committed in a single HTTP request:

```json
{
  "_id": "673abc000000000000000099",
  "_class": "core:class:TxApplyIf",
  "objectSpace": "673abc999999999999999999",
  "txes": [
    {
      "_id": "673abc000000000000000001",
      "_class": "core:class:TxCreateDoc",
      "objectId": "673abc111111111111111111",
      "objectClass": "testManagement:class:TestRun",
      "objectSpace": "673abc999999999999999999",
      "attributes": {
        "name": "Pytest CI Run #120",
        "description": null
      }
    },
    {
      "_id": "673abc000000000000000002",
      "_class": "core:class:TxCreateDoc",
      "objectId": "673abc222222222222222222",
      "objectClass": "testManagement:class:TestResult",
      "objectSpace": "673abc999999999999999999",
      "attachedTo": "673abc111111111111111111",
      "attachedToClass": "testManagement:class:TestRun",
      "collection": "results",
      "attributes": {
        "name": "test_login",
        "testCase": "673abc333333333333333333",
        "status": 2
      }
    }
  ]
}
```

---

## 3. Standalone External Ingestion Service Architecture

### 3.1 Overview & Benefits
The **Huly Test Ingestion Service (`huly-test-ingest`)** is a standalone bridge service deployed alongside Huly or in CI environments.

```
+------------------+         +----------------------------+         +----------------------+
| CI/CD Pipeline   |  POST   |  huly-test-ingest Service  |  POST   |  Huly Transactor     |
| - Pytest         |-------->|  - Parses JUnit XML/JSON   |-------->|  - Validates Auth    |
| - Jest / Vitest  |  /junit |  - Resolves Suites & Cases |  /tx    |  - Commits TxApplyIf |
| - Playwright     |  /json  |  - Auto-creates missing    |         |  - Persists to DB    |
| - JUnit 5        |         |  - Batch Chunks (100 tx/req|         +----------------------+
+------------------+         +----------------------------+
```

**Key Capabilities**:
1. **Universal Report Parser**: Accepts standard JUnit XML, Pytest JSON, Cucumber JSON, and Allure JSON reports.
2. **Deduplication & Entity Resolution**: Maps test classes to Huly `TestSuite`s, and test method names to Huly `TestCase`s.
3. **Auto-Provisioning**: Automatically creates missing `TestSuite`s and `TestCase`s if configured (`auto_create_cases = true`).
4. **Resilience & Rate-Limiting**: Batches results into chunks of 50–100 transactions, retrying on HTTP 429 (`Retry-After`).
5. **Swagger / OpenAPI Documentation**: Exposes interactive docs at `/docs`.

---

### 3.2 FastAPI Implementation Specification

Below is the complete architectural implementation of the FastAPI Ingestion Service.

#### `service/models.py`
```python
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
    name: str = Field(..., description="Test name or function identifier")
    suite_name: Optional[str] = Field(None, description="Parent test suite or module name")
    case_id: Optional[str] = Field(None, description="Existing Huly TestCase ID if known")
    status: TestRunStatusEnum = Field(..., description="Test execution status (0-3)")
    duration_ms: Optional[float] = Field(None, description="Execution duration in milliseconds")
    error_message: Optional[str] = Field(None, description="Failure summary or assertion message")
    error_trace: Optional[str] = Field(None, description="Full failure stack trace or log")

class CreateIngestRunRequest(BaseModel):
    project_id: str = Field(..., description="Target Huly TestProject ID (24-char hex)")
    run_name: str = Field(..., description="Descriptive name for the test run")
    run_id: Optional[str] = Field(None, description="Existing TestRun ID to append results to")
    auto_create_cases: bool = Field(True, description="Auto-create missing TestSuites and TestCases")
    results: List[IngestTestResultItem] = Field(default_factory=list)

class IngestRunResponse(BaseModel):
    success: bool
    run_id: str
    total_results: int
    passed: int
    failed: int
    blocked: int
    test_run_url: str
```

#### `service/transactor_client.py`
```python
import os
import time
import secrets
from typing import Any, Dict, List, Optional
import httpx

class HulyTransactorClient:
    def __init__(self, base_url: str, workspace_id: str, api_token: str):
        self.base_url = base_url.rstrip("/")
        self.workspace_id = workspace_id
        self.api_token = api_token
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }
        self.client = httpx.AsyncClient(timeout=30.0)

    @staticmethod
    def generate_id() -> str:
        t = f"{int(time.time()):08x}"
        r = secrets.token_hex(5)
        c = secrets.token_hex(3)
        return f"{t}{r}{c}"

    async def ping(self) -> Dict[str, Any]:
        resp = await self.client.get(
            f"{self.base_url}/api/v1/ping/{self.workspace_id}",
            headers=self.headers,
        )
        resp.raise_for_status()
        return resp.json()

    async def find_all(self, doc_class: str, query: Dict[str, Any], limit: int = 100) -> List[Dict[str, Any]]:
        payload = {
            "_class": doc_class,
            "query": query,
            "options": {"limit": limit},
        }
        resp = await self.client.post(
            f"{self.base_url}/api/v1/find-all/{self.workspace_id}",
            headers=self.headers,
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    async def commit_tx(self, tx: Dict[str, Any]) -> Any:
        resp = await self.client.post(
            f"{self.base_url}/api/v1/tx/{self.workspace_id}",
            headers=self.headers,
            json=tx,
        )
        resp.raise_for_status()
        return resp.json()

    async def commit_batch(self, space_id: str, tx_list: List[Dict[str, Any]]) -> None:
        """Commit a batch of transactions using TxApplyIf in chunks of 50."""
        chunk_size = 50
        for i in range(0, len(tx_list), chunk_size):
            chunk = tx_list[i : i + chunk_size]
            batch_tx = {
                "_id": self.generate_id(),
                "_class": "core:class:TxApplyIf",
                "objectSpace": space_id,
                "txes": chunk,
            }
            await self.commit_tx(batch_tx)
```

#### `service/main.py`
```python
import xml.etree.ElementTree as ET
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from service.models import (
    CreateIngestRunRequest,
    IngestRunResponse,
    IngestTestResultItem,
    TestRunStatusEnum,
)
from service.transactor_client import HulyTransactorClient

app = FastAPI(
    title="Huly Test Ingestion API",
    description="Universal CI/CD test results ingestion service for Huly Test Management",
    version="1.0.0",
)

@app.post("/api/v1/ingest/run", response_model=IngestRunResponse)
async def ingest_run(
    req: CreateIngestRunRequest,
    huly_url: str,
    huly_workspace: str,
    huly_token: str,
):
    client = HulyTransactorClient(huly_url, huly_workspace, huly_token)
    
    # 1. Resolve or Create TestRun
    run_id = req.run_id or client.generate_id()
    transactions = []
    
    if not req.run_id:
        transactions.append({
            "_id": client.generate_id(),
            "_class": "core:class:TxCreateDoc",
            "objectId": run_id,
            "objectClass": "testManagement:class:TestRun",
            "objectSpace": req.project_id,
            "attributes": {
                "name": req.run_name,
                "description": None,
                "dueDate": int(time.time() * 1000),
            },
        })

    # 2. Cache existing TestSuites and TestCases to avoid duplicate creation
    existing_suites = {
        s["name"]: s["_id"]
        for s in await client.find_all("testManagement:class:TestSuite", {"space": req.project_id})
    }
    existing_cases = {
        c["name"]: c["_id"]
        for c in await client.find_all("testManagement:class:TestCase", {"space": req.project_id})
    }

    passed, failed, blocked = 0, 0, 0

    # 3. Process test results
    for item in req.results:
        suite_id = None
        if item.suite_name:
            if item.suite_name not in existing_suites and req.auto_create_cases:
                suite_id = client.generate_id()
                transactions.append({
                    "_id": client.generate_id(),
                    "_class": "core:class:TxCreateDoc",
                    "objectId": suite_id,
                    "objectClass": "testManagement:class:TestSuite",
                    "objectSpace": req.project_id,
                    "attributes": {
                        "name": item.suite_name,
                        "description": "",
                        "parent": "testManagement:ids:NoParent",
                    },
                })
                existing_suites[item.suite_name] = suite_id
            else:
                suite_id = existing_suites.get(item.suite_name)

        case_id = item.case_id or existing_cases.get(item.name)
        if not case_id and req.auto_create_cases and suite_id:
            case_id = client.generate_id()
            transactions.append({
                "_id": client.generate_id(),
                "_class": "core:class:TxCreateDoc",
                "objectId": case_id,
                "objectClass": "testManagement:class:TestCase",
                "objectSpace": req.project_id,
                "attachedTo": suite_id,
                "attachedToClass": "testManagement:class:TestSuite",
                "collection": "testCases",
                "attributes": {
                    "name": item.name,
                    "description": None,
                    "type": 0,      # Functional
                    "priority": 1,  # Medium
                    "status": 3,    # Approved
                    "assignee": None,
                },
            })
            existing_cases[item.name] = case_id

        # Format failure trace or error note into description
        desc = None
        if item.error_trace or item.error_message:
            desc = f"{item.error_message or ''}\n\n{item.error_trace or ''}".strip()

        # Add TestResult
        result_id = client.generate_id()
        transactions.append({
            "_id": client.generate_id(),
            "_class": "core:class:TxCreateDoc",
            "objectId": result_id,
            "objectClass": "testManagement:class:TestResult",
            "objectSpace": req.project_id,
            "attachedTo": run_id,
            "attachedToClass": "testManagement:class:TestRun",
            "collection": "results",
            "attributes": {
                "name": item.name,
                "testCase": case_id,
                "testSuite": suite_id,
                "status": int(item.status),
                "description": desc,
            },
        })

        if item.status == TestRunStatusEnum.PASSED:
            passed += 1
        elif item.status == TestRunStatusEnum.FAILED:
            failed += 1
        else:
            blocked += 1

    # 4. Commit batch transactions to Huly Transactor
    await client.commit_batch(req.project_id, transactions)

    return IngestRunResponse(
        success=True,
        run_id=run_id,
        total_results=len(req.results),
        passed=passed,
        failed=failed,
        blocked=blocked,
        test_run_url=f"{huly_url}/{huly_workspace}/test-management/runs/{run_id}",
    )

@app.post("/api/v1/ingest/junit", response_model=IngestRunResponse)
async def ingest_junit(
    file: UploadFile = File(...),
    project_id: str = Form(...),
    run_name: str = Form(...),
    huly_url: str = Form(...),
    huly_workspace: str = Form(...),
    huly_token: str = Form(...),
    auto_create: bool = Form(True),
):
    """Parse standard JUnit XML file and ingest into Huly."""
    contents = await file.read()
    root = ET.fromstring(contents)
    
    results = []
    for testcase in root.iter("testcase"):
        name = testcase.get("name")
        classname = testcase.get("classname", "DefaultSuite")
        time_s = float(testcase.get("time", "0"))
        
        status = TestRunStatusEnum.PASSED
        err_msg, err_trace = None, None
        
        failure = testcase.find("failure")
        error = testcase.find("error")
        skipped = testcase.find("skipped")
        
        if failure is not None:
            status = TestRunStatusEnum.FAILED
            err_msg = failure.get("message")
            err_trace = failure.text
        elif error is not None:
            status = TestRunStatusEnum.FAILED
            err_msg = error.get("message")
            err_trace = error.text
        elif skipped is not None:
            status = TestRunStatusEnum.BLOCKED
            err_msg = skipped.get("message")
            
        results.append(
            IngestTestResultItem(
                name=name,
                suite_name=classname,
                status=status,
                duration_ms=time_s * 1000,
                error_message=err_msg,
                error_trace=err_trace,
            )
        )
        
    req = CreateIngestRunRequest(
        project_id=project_id,
        run_name=run_name,
        auto_create_cases=auto_create,
        results=results,
    )
    return await ingest_run(req, huly_url, huly_workspace, huly_token)
```

---

## 4. `pytest-huly`: Python Pytest Plugin Specification

The `pytest-huly` package is an open-source Pytest plugin designed for automated test execution tracking.

### 4.1 Package Architecture

```
pytest-huly/
├── pyproject.toml
├── README.md
├── pytest_huly/
│   ├── __init__.py
│   ├── plugin.py          # Pytest hooks (makereport, sessionfinish, etc.)
│   ├── client.py          # Asynchronous Huly Transactor client
│   ├── config.py          # Config loader (CLI, env, huly.toml, pyproject.toml)
│   ├── models.py          # Pydantic entity models and enums
│   ├── id_generator.py    # 24-character hex ID generation
│   └── markers.py         # Pytest decorator markers (@pytest.mark.huly)
└── tests/
    └── test_plugin.py
```

#### `pyproject.toml` Registration
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "pytest-huly"
version = "0.1.0"
description = "Pytest plugin for Huly Test Management integration"
dependencies = [
    "pytest>=7.0.0",
    "httpx>=0.25.0",
    "pydantic>=2.0.0",
]

[project.entry-points.pytest11]
huly = "pytest_huly.plugin"
```

---

### 4.2 Pytest Lifecycle Hook Integration

```
                 Pytest Execution Flow
                           |
             [pytest_addoption]
             Register CLI flags (--huly, --huly-project, etc.)
                           |
             [pytest_configure]
             Load huly.toml / ENV / CLI args
             Validate API Token via /api/v1/ping
                           |
             [pytest_sessionstart]
             Create or locate TestRun in Huly
             (Generate 24-char run_id, record git commit & branch)
                           |
             [pytest_collection_finish]
             Discover all test cases & parent suites
             Optionally auto-create missing TestCases
                           |
             +---------------------------+
             | Loop each test execution: |
             |                           |
             | [pytest_runtest_makereport]
             | Intercept call / setup outcome
             | Status: passed -> 2, failed -> 3, skipped -> 1
             | Capture tracebacks, duration, and stdout
             +---------------------------+
                           |
             [pytest_sessionfinish]
             Assemble atomic TxApplyIf batch transaction
             POST to /api/v1/tx/:workspaceId
             Print Huly Test Run URL to terminal output
```

---

### 4.3 Detailed Implementation Code

#### 4.3.1 `pytest_huly/markers.py`
```python
import pytest

def huly(case_id: str = None, suite: str = None, priority: str = "medium", type: str = "functional"):
    """
    Pytest marker to link tests directly to Huly Test Management.

    Example:
        @pytest.mark.huly(case_id="673abc111111111111111111")
        def test_payment():
            ...
    """
    return pytest.mark.huly(case_id=case_id, suite=suite, priority=priority, type=type)
```

#### 4.3.2 `pytest_huly/config.py`
```python
import os
import tomllib
from dataclasses import dataclass
from typing import Optional

@dataclass
class HulyConfig:
    enabled: bool = False
    url: str = ""
    workspace: str = ""
    token: str = ""
    project: str = ""
    run_name: Optional[str] = None
    run_id: Optional[str] = None
    auto_create: bool = True
    ingestion_service_url: Optional[str] = None

def load_huly_config(pytest_config) -> HulyConfig:
    cfg = HulyConfig()

    # 1. Read from pyproject.toml or huly.toml if present
    for config_file in ["huly.toml", "pyproject.toml"]:
        if os.path.exists(config_file):
            with open(config_file, "rb") as f:
                data = tomllib.load(f)
                huly_section = data.get("tool", {}).get("huly") if "pyproject.toml" in config_file else data
                if huly_section:
                    cfg.url = huly_section.get("url", cfg.url)
                    cfg.workspace = huly_section.get("workspace", cfg.workspace)
                    cfg.token = huly_section.get("token", cfg.token)
                    cfg.project = huly_section.get("project", cfg.project)
                    cfg.auto_create = huly_section.get("auto_create", cfg.auto_create)
                    cfg.ingestion_service_url = huly_section.get("ingestion_service_url")

    # 2. Environment Variables override config files
    cfg.url = os.getenv("HULY_URL", cfg.url)
    cfg.workspace = os.getenv("HULY_WORKSPACE", cfg.workspace)
    cfg.token = os.getenv("HULY_TOKEN", cfg.token)
    cfg.project = os.getenv("HULY_PROJECT", cfg.project)
    if os.getenv("HULY_INGESTION_SERVICE_URL"):
        cfg.ingestion_service_url = os.getenv("HULY_INGESTION_SERVICE_URL")

    # 3. CLI options take top priority
    if pytest_config.getoption("--huly", default=False):
        cfg.enabled = True
    if pytest_config.getoption("--huly-url", default=None):
        cfg.url = pytest_config.getoption("--huly-url")
    if pytest_config.getoption("--huly-workspace", default=None):
        cfg.workspace = pytest_config.getoption("--huly-workspace")
    if pytest_config.getoption("--huly-token", default=None):
        cfg.token = pytest_config.getoption("--huly-token")
    if pytest_config.getoption("--huly-project", default=None):
        cfg.project = pytest_config.getoption("--huly-project")
    if pytest_config.getoption("--huly-run-name", default=None):
        cfg.run_name = pytest_config.getoption("--huly-run-name")
    if pytest_config.getoption("--huly-run-id", default=None):
        cfg.run_id = pytest_config.getoption("--huly-run-id")
    if pytest_config.getoption("--huly-no-auto-create", default=False):
        cfg.auto_create = False

    return cfg
```

#### 4.3.3 `pytest_huly/plugin.py`
```python
import datetime
import subprocess
import time
import pytest
from pytest_huly.config import HulyConfig, load_huly_config
from pytest_huly.client import HulyClient
from pytest_huly.models import TestRunStatusEnum

def pytest_addoption(parser):
    group = parser.getgroup("huly", "Huly Test Management integration")
    group.addoption("--huly", action="store_true", default=False, help="Enable Huly test reporting")
    group.addoption("--huly-url", help="Huly Transactor or Ingestion URL")
    group.addoption("--huly-workspace", help="Huly Workspace UUID")
    group.addoption("--huly-token", help="Huly API Token")
    group.addoption("--huly-project", help="Huly TestProject Space ID (24-hex)")
    group.addoption("--huly-run-name", help="Custom name for the Huly TestRun")
    group.addoption("--huly-run-id", help="Existing TestRun ID to attach results to")
    group.addoption("--huly-no-auto-create", action="store_true", default=False, help="Disable auto-creation of missing test cases")

class HulySessionPlugin:
    def __init__(self, config: HulyConfig):
        self.config = config
        self.client = HulyClient(config.url, config.workspace, config.token)
        self.run_id = config.run_id or self.client.generate_id()
        self.results = []
        self.existing_suites = {}
        self.existing_cases = {}

    def get_git_info(self) -> str:
        try:
            branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True).strip()
            commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
            return f"{branch} @ {commit}"
        except Exception:
            return "unknown"

    def pytest_sessionstart(self, session):
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        git_info = self.get_git_info()
        run_name = self.config.run_name or f"Pytest Run - {now_str} ({git_info})"
        
        # Pre-create TestRun transaction if not using existing run
        if not self.config.run_id:
            self.client.queue_create_test_run(
                run_id=self.run_id,
                space_id=self.config.project,
                name=run_name,
            )
            print(f"\n[Huly] Initialized TestRun: {run_name} (ID: {self.run_id})")

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        outcome = yield
        rep = outcome.get_result()

        # Only record final result during the 'call' phase, or 'setup' if setup failed
        if rep.when == "call" or (rep.when == "setup" and rep.failed):
            # Extract marker if provided
            huly_marker = item.get_closest_marker("huly")
            marker_case_id = huly_marker.kwargs.get("case_id") if huly_marker else None
            marker_suite = huly_marker.kwargs.get("suite") if huly_marker else None

            # Determine suite and test case names
            module_name = marker_suite or item.module.__name__
            test_name = item.name

            # Status mapping
            if rep.passed:
                status = TestRunStatusEnum.PASSED
            elif rep.failed:
                status = TestRunStatusEnum.FAILED
            else:
                status = TestRunStatusEnum.BLOCKED

            # Format error details
            error_trace = None
            if rep.failed:
                error_trace = str(rep.longrepr)

            self.results.append({
                "name": test_name,
                "suite_name": module_name,
                "case_id": marker_case_id,
                "status": status,
                "duration": rep.duration,
                "error_trace": error_trace,
            })

    def pytest_sessionfinish(self, session, exitstatus):
        if not self.results:
            return

        print(f"\n[Huly] Synchronizing {len(self.results)} test results to Huly...")
        self.client.sync_results(
            project_id=self.config.project,
            run_id=self.run_id,
            results=self.results,
            auto_create=self.config.auto_create,
        )
        url = f"{self.config.url.replace(':3332', ':8087')}/{self.config.workspace}/test-management/runs/{self.run_id}"
        print(f"[Huly] Test Run completed! View report in Huly: {url}\n")

def pytest_configure(config):
    huly_config = load_huly_config(config)
    if huly_config.enabled:
        plugin = HulySessionPlugin(huly_config)
        config.pluginmanager.register(plugin, "huly_session")
```

---

## 5. End-to-End Configuration & Usage

### 5.1 Project Configuration (`huly.toml`)
Place `huly.toml` at the root of the test repository:

```toml
[huly]
url = "http://huly.local:3332"
workspace = "4722513f-801e-4581-9b62-677f59d58434"
project = "673abc999999999999999999"
auto_create = true

# Optional: route through huly-test-ingest microservice instead of direct Transactor
# ingestion_service_url = "http://huly-ingest.local:8000"
```

### 5.2 Writing Pytests with Huly Markers
```python
import pytest

# Case 1: Auto-inferred suite and test case
def test_user_profile_fetch():
    assert 200 == 200

# Case 2: Explicitly linking to an existing Huly Test Case ID
@pytest.mark.huly(case_id="673abc222222222222222222")
def test_stripe_webhook_idempotency():
    assert True

# Case 3: Specifying custom suite and priority for auto-creation
@pytest.mark.huly(suite="Billing & Invoicing", priority="urgent", type="functional")
def test_refund_processing():
    assert 1 + 1 == 2
```

### 5.3 Running in CI/CD (GitHub Actions Example)

```yaml
name: Test Suite & Huly Reporting

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install pytest pytest-huly httpx

      - name: Run Pytest with Huly reporting
        env:
          HULY_URL: ${{ secrets.HULY_TRANSACTOR_URL }}
          HULY_WORKSPACE: ${{ secrets.HULY_WORKSPACE_UUID }}
          HULY_TOKEN: ${{ secrets.HULY_API_TOKEN }}
          HULY_PROJECT: ${{ secrets.HULY_TEST_PROJECT_ID }}
        run: |
          pytest --huly \
            --huly-run-name="GitHub Actions Run #${{ github.run_number }} (${{ github.ref_name }})"
```

---

## 6. Implementation & Roadmap Summary

| Phase | Milestone | Deliverable |
|---|---|---|
| **Phase 1** | Model & Mutation Foundations | Verified `TxCreateDoc` / `TxCollectionCUD` batch execution against CockroachDB storage domain `test-management`. |
| **Phase 2** | `huly-test-ingest` Microservice | Containerized FastAPI ingestion service exposing `/api/v1/ingest/junit` and `/api/v1/ingest/run` with Swagger docs. |
| **Phase 3** | `pytest-huly` Package | PyPI publishable Python package with Pytest hooks, marker support, and local 24-character ID generation. |
| **Phase 4** | Web UI Enhancements | Real-time live execution ticker in `TestRunStats.svelte`, showing live passed/failed counters as CI tests run. |

---

*Authored by Test Management & Integration Specialist (`test_integration_engineer`)*  
*Huly Platform Research Team*
