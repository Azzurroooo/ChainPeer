"""Main FastAPI application definition."""

from fastapi import FastAPI
from agent.interfaces.api.routes_session import router as session_router
from agent.interfaces.api.routes_job import router as job_router

def create_app() -> FastAPI:
    app = FastAPI(title="ChainPeer API", version="1.0.0")
    app.include_router(session_router)
    app.include_router(job_router)
    return app
