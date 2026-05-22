"""Main FastAPI application definition."""

from fastapi import FastAPI
from agent.interfaces.api.routes_session import router as session_router
from agent.interfaces.api.routes_job import router as job_router
from agent.bootstrap.container import build_basic_agent_dependencies

def create_app() -> FastAPI:
    app = FastAPI(title="Quanora API", version="1.0.0")
    
    # Initialize dependencies on startup
    deps = build_basic_agent_dependencies()
    app.state.job_service = deps["job_service"]
    
    # In a real app, agent_factory would build a new runtime for each session.
    # Here we just wrap the DI container's creation.
    def _agent_factory(session_id: str):
        session_deps = build_basic_agent_dependencies(session_id=session_id)
        return session_deps["runtime"]
        
    app.state.agent_factory = _agent_factory
    
    app.include_router(session_router)
    app.include_router(job_router)
    return app
