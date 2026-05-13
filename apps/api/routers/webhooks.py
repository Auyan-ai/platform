import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/zendesk")
async def zendesk_webhook(request: Request, background_tasks: BackgroundTasks) -> dict:
    payload = await request.json()
    logger.info("Zendesk webhook received", extra={"payload_keys": list(payload.keys())})
    # TODO: procesar en background_tasks cuando la integración Zendesk esté lista
    return {"received": True}


@router.post("/chatwoot")
async def chatwoot_webhook(request: Request, background_tasks: BackgroundTasks) -> dict:
    payload = await request.json()
    logger.info("Chatwoot webhook received", extra={"event": payload.get("event")})
    return {"received": True}


@router.post("/postmark")
async def postmark_webhook(request: Request, background_tasks: BackgroundTasks) -> dict:
    payload: dict[str, Any] = await request.json()
    logger.info("Postmark webhook received", extra={"from": payload.get("From")})
    return {"received": True}
