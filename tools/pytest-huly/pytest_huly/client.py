"""
Huly Client for pytest-huly
Handles batch transactions, ID generation, and communication with Huly Transactor or Ingestion service.
"""

import time
import secrets
from typing import Any, Dict, List, Optional
import httpx


def generate_huly_id() -> str:
    """Generate a 24-character hexadecimal ID matching Huly's generateId() algorithm."""
    ts = f"{int(time.time()):08x}"
    rnd = secrets.token_hex(5)
    cnt = secrets.token_hex(3)
    return f"{ts}{rnd}{cnt}"


class HulyClient:
    def __init__(
        self,
        base_url: str,
        workspace_id: str,
        api_token: str,
        ingest_service_url: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.workspace_id = workspace_id
        self.api_token = api_token
        self.ingest_service_url = ingest_service_url.rstrip("/") if ingest_service_url else None
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }
        self.client = httpx.Client(timeout=30.0)

    def close(self):
        self.client.close()

    def ping(self) -> Dict[str, Any]:
        resp = self.client.get(
            f"{self.base_url}/api/v1/ping/{self.workspace_id}",
            headers=self.headers,
        )
        resp.raise_for_status()
        return resp.json()

    def sync_via_ingest_service(
        self,
        project_id: str,
        run_name: str,
        run_id: str,
        results: List[Dict[str, Any]],
        auto_create: bool = True,
    ) -> Dict[str, Any]:
        """Send results via the standalone huly-test-ingest service."""
        payload = {
            "project_id": project_id,
            "run_name": run_name,
            "run_id": run_id,
            "auto_create_cases": auto_create,
            "results": results,
        }
        headers = {
            "X-Huly-Url": self.base_url,
            "X-Huly-Workspace": self.workspace_id,
            "X-Huly-Token": self.api_token,
            "Content-Type": "application/json",
        }
        resp = self.client.post(
            f"{self.ingest_service_url}/api/v1/ingest/run",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    def sync_via_transactor(
        self,
        project_id: str,
        run_name: str,
        run_id: str,
        results: List[Dict[str, Any]],
        auto_create: bool = True,
    ) -> None:
        """Send results directly to Huly Transactor using TxApplyIf batches."""
        transactions = []

        # 1. Create TestRun
        transactions.append({
            "_id": generate_huly_id(),
            "_class": "core:class:TxCreateDoc",
            "objectId": run_id,
            "objectClass": "testManagement:class:TestRun",
            "objectSpace": project_id,
            "attributes": {
                "name": run_name,
                "description": None,
                "dueDate": int(time.time() * 1000),
            },
        })

        # 2. Query existing suites and cases for deduplication
        existing_suites = {}
        existing_cases = {}
        try:
            resp_suites = self.client.post(
                f"{self.base_url}/api/v1/find-all/{self.workspace_id}",
                headers=self.headers,
                json={"_class": "testManagement:class:TestSuite", "query": {"space": project_id}},
            )
            if resp_suites.status_code == 200:
                for s in resp_suites.json():
                    if "name" in s and "_id" in s:
                        existing_suites[s["name"]] = s["_id"]

            resp_cases = self.client.post(
                f"{self.base_url}/api/v1/find-all/{self.workspace_id}",
                headers=self.headers,
                json={"_class": "testManagement:class:TestCase", "query": {"space": project_id}},
            )
            if resp_cases.status_code == 200:
                for c in resp_cases.json():
                    if "name" in c and "_id" in c:
                        existing_cases[c["name"]] = c["_id"]
        except Exception:
            pass

        # 3. Create test cases and results
        for item in results:
            suite_name = item.get("suite_name")
            suite_id = None
            if suite_name:
                if suite_name not in existing_suites and auto_create:
                    suite_id = generate_huly_id()
                    transactions.append({
                        "_id": generate_huly_id(),
                        "_class": "core:class:TxCreateDoc",
                        "objectId": suite_id,
                        "objectClass": "testManagement:class:TestSuite",
                        "objectSpace": project_id,
                        "attributes": {
                            "name": suite_name,
                            "description": "",
                            "parent": "testManagement:ids:NoParent",
                        },
                    })
                    existing_suites[suite_name] = suite_id
                else:
                    suite_id = existing_suites.get(suite_name)

            case_name = item["name"]
            case_id = item.get("case_id") or existing_cases.get(case_name)
            if not case_id and auto_create and suite_id:
                case_id = generate_huly_id()
                transactions.append({
                    "_id": generate_huly_id(),
                    "_class": "core:class:TxCreateDoc",
                    "objectId": case_id,
                    "objectClass": "testManagement:class:TestCase",
                    "objectSpace": project_id,
                    "attachedTo": suite_id,
                    "attachedToClass": "testManagement:class:TestSuite",
                    "collection": "testCases",
                    "attributes": {
                        "name": case_name,
                        "description": None,
                        "type": 0,      # Functional
                        "priority": 1,  # Medium
                        "status": 3,    # Approved
                        "assignee": None,
                    },
                })
                existing_cases[case_name] = case_id

            # Add TestResult
            result_id = generate_huly_id()
            desc = None
            if item.get("error_trace"):
                desc = item["error_trace"].strip()

            transactions.append({
                "_id": generate_huly_id(),
                "_class": "core:class:TxCreateDoc",
                "objectId": result_id,
                "objectClass": "testManagement:class:TestResult",
                "objectSpace": project_id,
                "attachedTo": run_id,
                "attachedToClass": "testManagement:class:TestRun",
                "collection": "results",
                "attributes": {
                    "name": case_name,
                    "testCase": case_id,
                    "testSuite": suite_id,
                    "status": int(item["status"]),
                    "description": desc,
                },
            })

        # 4. Commit batch in chunks of 50
        chunk_size = 50
        for i in range(0, len(transactions), chunk_size):
            chunk = transactions[i : i + chunk_size]
            batch_tx = {
                "_id": generate_huly_id(),
                "_class": "core:class:TxApplyIf",
                "objectSpace": project_id,
                "txes": chunk,
            }
            resp = self.client.post(
                f"{self.base_url}/api/v1/tx/{self.workspace_id}",
                headers=self.headers,
                json=batch_tx,
            )
            resp.raise_for_status()
