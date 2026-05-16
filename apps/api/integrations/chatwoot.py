import logging
from typing import Any

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


class ChatwootClient:
    def __init__(self) -> None:
        self.base_url = settings.chatwoot_base_url.rstrip("/")
        self.token = settings.chatwoot_api_token

    def _headers(self) -> dict:
        return {"api_access_token": self.token, "Content-Type": "application/json"}

    async def send_message(
        self, account_id: int, conversation_id: int, content: str, message_type: str = "outgoing"
    ) -> dict[str, Any]:
        url = (
            f"{self.base_url}/api/v1/accounts/{account_id}"
            f"/conversations/{conversation_id}/messages"
        )
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=self._headers(),
                json={"content": content, "message_type": message_type},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()

    async def assign_conversation(
        self, account_id: int, conversation_id: int, assignee_id: int
    ) -> dict[str, Any]:
        url = (
            f"{self.base_url}/api/v1/accounts/{account_id}"
            f"/conversations/{conversation_id}/assignments"
        )
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                headers=self._headers(),
                json={"assignee_id": assignee_id},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()


chatwoot = ChatwootClient()
