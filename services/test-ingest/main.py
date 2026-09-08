"""
Huly External Test Ingestion Service
Exposes REST endpoints for ingesting CI/CD test results (JUnit XML, JSON) into Huly Test Management.
"""

import os
import time
import xml.etree.ElementTree as ET
from typing import Optional
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile, Depends
from fastapi.middleware.cors import CORSMiddleware

from models import (
    CreateIngestRunRequest,
    IngestRunResponse,
    IngestTestResultItem,
    TestRunStatusEnum,
)
from transactor import HulyTransactorClient, generate_huly_id

app = FastAPI(
    title="Huly Test Ingestion Service",
    description="Universal CI/CD test results ingestion API for Huly Test Management",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "huly-test-ingest"}


@app.post("/api/v1/ingest/run", response_model=IngestRunResponse)
async def ingest_run(
    req: CreateIngestRunRequest,
    huly_url: str = Header(..., alias="X-Huly-Url"),
    huly_workspace: str = Header(..., alias="X-Huly-Workspace"),
    huly_token: str = Header(..., alias="X-Huly-Token"),
):
    """
    Ingest structured JSON test results into Huly Test Management.
    """
    client = HulyTransactorClient(huly_url, huly_workspace, huly_token)
    try:
        run_id = req.run_id or generate_huly_id()
        transactions = []

        # 1. Create TestRun if not appending to existing run
        if not req.run_id:
            transactions.append({
                "_id": generate_huly_id(),
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

        # 2. Query existing suites and cases for deduplication
        existing_suites = {}
        existing_cases = {}
        try:
            suites = await client.find_all("testManagement:class:TestSuite", {"space": req.project_id})
            existing_suites = {s["name"]: s["_id"] for s in suites if "name" in s and "_id" in s}
            cases = await client.find_all("testManagement:class:TestCase", {"space": req.project_id})
            existing_cases = {c["name"]: c["_id"] for c in cases if "name" in c and "_id" in c}
        except Exception:
            pass

        passed, failed, blocked = 0, 0, 0

        # 3. Assemble mutations for each test result
        for item in req.results:
            suite_id = None
            if item.suite_name:
                if item.suite_name not in existing_suites and req.auto_create_cases:
                    suite_id = generate_huly_id()
                    transactions.append({
                        "_id": generate_huly_id(),
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
                case_id = generate_huly_id()
                transactions.append({
                    "_id": generate_huly_id(),
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

            desc = None
            if item.error_trace or item.error_message:
                desc = f"{item.error_message or ''}\n\n{item.error_trace or ''}".strip()

            result_id = generate_huly_id()
            transactions.append({
                "_id": generate_huly_id(),
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
    finally:
        await client.close()


@app.post("/api/v1/ingest/junit", response_model=IngestRunResponse)
async def ingest_junit(
    file: UploadFile = File(...),
    project_id: str = Form(...),
    run_name: str = Form(...),
    huly_url: str = Header(..., alias="X-Huly-Url"),
    huly_workspace: str = Header(..., alias="X-Huly-Workspace"),
    huly_token: str = Header(..., alias="X-Huly-Token"),
    auto_create: bool = Form(True),
):
    """
    Parse standard JUnit XML file and ingest into Huly Test Management.
    """
    contents = await file.read()
    try:
        root = ET.fromstring(contents)
    except ET.ParseError as e:
        raise HTTPException(status_code=400, detail=f"Invalid XML: {e}")

    results = []
    for testcase in root.iter("testcase"):
        name = testcase.get("name", "Unnamed Test")
        classname = testcase.get("classname", "DefaultSuite")
        try:
            time_s = float(testcase.get("time", "0"))
        except ValueError:
            time_s = 0.0

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


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8095"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
