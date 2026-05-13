import logging
from typing import Any

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


class ZendeskClient:
    def __init__(self) -> None:
        self.subdomain = settings.zendesk_subdomain
        self.email = settings.zendesk_email
        self.token = settings.zendesk_api_token

    @property
    def base_url(self) -> str:
        return f"https://{self.subdomain}.zendesk.com/api/v2"

    def _auth(self) -> tuple[str, str]:
        return (f"{self.email}/token", self.token)

    async def get_ticket(self, ticket_id: int) -> dict[str, Any]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/tickets/{ticket_id}.json",
                auth=self._auth(),
                timeout=10,
            )
            response.raise_for_status()
            return response.json()["ticket"]

    async def add_comment(self, ticket_id: int, body: str, public: bool = True) -> dict[str, Any]:
        async with httpx.AsyncClient() as client:
            response = await client.put(
                f"{self.base_url}/tickets/{ticket_id}.json",
                auth=self._auth(),
                json={"ticket": {"comment": {"body": body, "public": public}}},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()["ticket"]


zendesk = ZendeskClient()
