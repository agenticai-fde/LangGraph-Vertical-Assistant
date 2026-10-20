"""FastAPI service for the HR / Healthcare / Finance assistants.

    uvicorn api:app --port 8004      then open http://127.0.0.1:8004/docs
"""
import os
import uuid
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from langchain_core.messages import HumanMessage
from ollama import ResponseError
from pydantic import BaseModel, Field

from graph import graph

API_KEY = os.getenv("API_KEY")  # when set, every request needs header X-API-Key
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(key: Optional[str] = Security(api_key_header)):
    if API_KEY and key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key.")


app = FastAPI(title="Vertical Assistants",
              description="One chat endpoint; a supervisor routes each message to the HR, "
                          "Healthcare or Finance assistant.",
              dependencies=[Depends(require_api_key)])


@app.exception_handler(ResponseError)
def llm_unavailable(request, exc: ResponseError):
    return JSONResponse(status_code=503, content={"detail": f"LLM unavailable: {exc.error}"})


class ChatRequest(BaseModel):
    message: str = Field(description="e.g. 'What is my leave balance? I am E101'")
    thread_id: Optional[str] = Field(None, description="Omit to start a new conversation")


class ChatResponse(BaseModel):
    thread_id: str
    domain: str = Field(description="hr, healthcare, finance, emergency or unknown")
    reply: str


@app.post("/chat", response_model=ChatResponse, operation_id="chat")
def chat(data: ChatRequest):
    thread_id = data.thread_id or uuid.uuid4().hex
    result = graph.invoke({"messages": [HumanMessage(data.message)]},
                          {"configurable": {"thread_id": thread_id}})
    return ChatResponse(thread_id=thread_id, domain=result["domain"],
                        reply=result["messages"][-1].content)


@app.get("/threads/{thread_id}", operation_id="getThread")
def get_thread(thread_id: str):
    state = graph.get_state({"configurable": {"thread_id": thread_id}}).values
    if not state:
        raise HTTPException(status_code=404, detail="Unknown thread (threads live in memory).")
    return {"thread_id": thread_id, "domain": state.get("domain"),
            "messages": [{"role": m.type, "content": m.content} for m in state["messages"]]}


@app.get("/health")
def health():
    return {"status": "ok"}
