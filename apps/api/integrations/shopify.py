import logging
from typing import Any

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


class ShopifyClient:
    def __init__(self, shop_domain: str, access_token: str) -> None:
        self.shop_domain = shop_domain.rstrip("/")
        self.access_token = access_token

    @property
    def base_url(self) -> str:
        return f"https://{self.shop_domain}/admin/api/2024-10"

    def _headers(self) -> dict:
        return {"X-Shopify-Access-Token": self.access_token, "Content-Type": "application/json"}

    async def get_order(self, order_id: int) -> dict[str, Any]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/orders/{order_id}.json",
                headers=self._headers(),
                timeout=10,
            )
            response.raise_for_status()
            return response.json()["order"]

    async def get_orders_by_email(self, email: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}/orders.json",
                headers=self._headers(),
                params={"email": email, "status": "any", "limit": 10},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()["orders"]

    async def cancel_order(self, order_id: int) -> dict[str, Any]:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/orders/{order_id}/cancel.json",
                headers=self._headers(),
                timeout=10,
            )
            response.raise_for_status()
            return response.json()["order"]
