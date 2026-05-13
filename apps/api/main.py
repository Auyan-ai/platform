from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from routers import tickets, tenants, webhooks


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="Auyan API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tickets.router, prefix="/tickets", tags=["tickets"])
app.include_router(tenants.router, prefix="/tenants", tags=["tenants"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "0.1.0"}
