"""
Huly Transactor REST RPC Client
Interacts with Transactor HTTP API on port 3332.
"""

import time
import secrets
from typing import Any, Dict, List, Optional
import httpx


def generate_huly_id() -> str:
    """Generate a 24-character hex ID matching Huly's generateId() specification."""
    ts = f"{int(time.time()):08x}"
    rnd = secrets.token_hex(5)
    cnt = secrets.token_hex(3)
    return f"{ts}{rnd}{cnt}"


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

    async def close(self):
        await self.client.aclose()

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
                "_id": generate_huly_id(),
                "_class": "core:class:TxApplyIf",
                "objectSpace": space_id,
                "txes": chunk,
            }
            await self.commit_tx(batch_tx)
