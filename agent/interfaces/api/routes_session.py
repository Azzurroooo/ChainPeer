"""FastAPI routes for session execution."""

from __future__ import annotations

import json
from typing import Any
from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel

from agent.application.runtime.cancellation import CancellationTokenSource

router = APIRouter(prefix="/sessions", tags=["sessions"])

class TurnRequest(BaseModel):
    query: str
    system_prompt: str | None = None

# A simple registry for injecting the agent dependencies per request.
# In a real app, this would be handled by FastAPI's DI properly.
def get_agent_factory(request: Request) -> Any:
    return request.app.state.agent_factory


@router.post("/{session_id}/turns")
async def run_turn(session_id: str, turn_req: TurnRequest, request: Request, factory=Depends(get_agent_factory)):
    """Run a single turn and stream the response events via SSE."""
    
    agent = factory(session_id=session_id)
    # Ensure initialization happens before running the turn
    await agent.initialize()
    
    # Optional system prompt override
    if turn_req.system_prompt:
        agent.session.system_prompt = turn_req.system_prompt

    # Persist the user's query before kicking off the runtime
    await agent.session.persist_message("user", turn_req.query)
    
    cancel_source = CancellationTokenSource()

    async def event_generator():
        try:
            async for event in agent.run_turn(cancellation_token=cancel_source.token):
                # Check for client disconnect
                if await request.is_disconnected():
                    cancel_source.cancel("Client disconnected")
                    break
                    
                # Convert the RuntimeEvent to a dict, then to JSON string
                # Note: You'd want a proper serialization method on RuntimeEvent
                event_dict = {
                    "type": event.type,
                    "ts": event.ts
                }
                if hasattr(event, "text"):
                    event_dict["text"] = event.text
                if hasattr(event, "tool_call_id"):
                    event_dict["tool_call_id"] = event.tool_call_id
                if hasattr(event, "tool_name"):
                    event_dict["tool_name"] = event.tool_name
                if hasattr(event, "payload"):
                    event_dict["payload"] = event.payload
                if hasattr(event, "result"):
                    event_dict["result"] = event.result
                if hasattr(event, "reason"):
                    event_dict["reason"] = event.reason
                    
                yield {
                    "event": event.type,
                    "data": json.dumps(event_dict, ensure_ascii=False)
                }
        except Exception as e:
            yield {
                "event": "error",
                "data": json.dumps({"error": str(e)})
            }

    return EventSourceResponse(event_generator())
