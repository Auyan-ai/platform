import uuid
from typing import Any

from supabase import Client


async def get_tenant_by_id(db: Client, tenant_id: uuid.UUID) -> dict | None:
    result = (
        db.table("tenants")
        .select("*")
        .eq("id", str(tenant_id))
        .is_("deleted_at", "null")
        .maybe_single()
        .execute()
    )
    return result.data


async def get_tenant_config(db: Client, tenant_id: uuid.UUID) -> dict | None:
    result = (
        db.table("tenant_configurations")
        .select("*")
        .eq("tenant_id", str(tenant_id))
        .maybe_single()
        .execute()
    )
    return result.data


async def get_active_prompt(db: Client, tenant_id: uuid.UUID, name: str) -> dict | None:
    result = (
        db.table("tenant_prompts")
        .select("*")
        .eq("tenant_id", str(tenant_id))
        .eq("name", name)
        .eq("is_active", True)
        .is_("deleted_at", "null")
        .maybe_single()
        .execute()
    )
    return result.data


async def get_conversation(db: Client, tenant_id: uuid.UUID, conversation_id: uuid.UUID) -> dict | None:
    result = (
        db.table("conversations")
        .select("*")
        .eq("id", str(conversation_id))
        .eq("tenant_id", str(tenant_id))
        .is_("deleted_at", "null")
        .maybe_single()
        .execute()
    )
    return result.data


async def create_conversation(db: Client, data: dict[str, Any]) -> dict:
    result = db.table("conversations").insert(data).execute()
    return result.data[0]


async def update_conversation(
    db: Client, tenant_id: uuid.UUID, conversation_id: uuid.UUID, data: dict[str, Any]
) -> dict:
    result = (
        db.table("conversations")
        .update(data)
        .eq("id", str(conversation_id))
        .eq("tenant_id", str(tenant_id))
        .execute()
    )
    return result.data[0]


async def get_conversation_messages(
    db: Client, tenant_id: uuid.UUID, conversation_id: uuid.UUID, limit: int = 50
) -> list[dict]:
    result = (
        db.table("messages")
        .select("*")
        .eq("conversation_id", str(conversation_id))
        .eq("tenant_id", str(tenant_id))
        .is_("deleted_at", "null")
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    return result.data


async def create_message(db: Client, data: dict[str, Any]) -> dict:
    result = db.table("messages").insert(data).execute()
    return result.data[0]


async def create_escalation(db: Client, data: dict[str, Any]) -> dict:
    result = db.table("escalations").insert(data).execute()
    return result.data[0]


async def get_or_create_end_customer(
    db: Client, tenant_id: uuid.UUID, email: str | None = None, external_id: str | None = None
) -> dict:
    if email:
        existing = (
            db.table("end_customers")
            .select("*")
            .eq("tenant_id", str(tenant_id))
            .eq("email", email.lower())
            .is_("deleted_at", "null")
            .maybe_single()
            .execute()
        )
        if existing.data:
            return existing.data

    payload: dict[str, Any] = {"tenant_id": str(tenant_id), "metadata": {}}
    if email:
        payload["email"] = email.lower()
    if external_id:
        payload["external_id"] = external_id

    result = db.table("end_customers").insert(payload).execute()
    return result.data[0]


async def search_knowledge_base(
    db: Client, tenant_id: uuid.UUID, embedding: list[float], match_count: int = 5
) -> list[dict]:
    result = db.rpc(
        "match_knowledge_base_chunks",
        {
            "query_embedding": embedding,
            "tenant_id_filter": str(tenant_id),
            "match_count": match_count,
        },
    ).execute()
    return result.data or []
