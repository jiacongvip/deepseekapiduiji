import httpx
from typing import Any, Dict


class SoraClient:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def _headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
        }
        if self.token:
            headers["Authorization"] = self.token
        return headers

    async def create_video_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/v1/videos/generations"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=self._headers(), timeout=60.0)
            resp.raise_for_status()
            return resp.json()

    async def create_character_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/v1/characters"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=self._headers(), timeout=60.0)
            resp.raise_for_status()
            return resp.json()

    async def get_task(self, task_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/v1/videos/tasks/{task_id}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=self._headers(), timeout=30.0)
            resp.raise_for_status()
            return resp.json()

    async def remix_video(self, video_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/v1/videos/{video_id}/remix"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=self._headers(), timeout=60.0)
            resp.raise_for_status()
            return resp.json()
