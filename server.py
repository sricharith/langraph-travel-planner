# server.py : uvicorn server:app --reload --port 8000
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import Dict, Any

from graph.travel_graph import build_graph

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# In-memory sessions for demo purposes
_SESSIONS: Dict[str, Dict[str, Any]] = {}

graph = build_graph()

class ChatIn(BaseModel):
    session_id: str
    message: str = ""
    preferences: list[str] | None = None

@app.get("/")
async def index():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.post("/chat")
async def chat(body: ChatIn):
    sid = body.session_id
    session = _SESSIONS.setdefault(sid, {
        "messages": [],
        "name": None,
        "destination": None,
        "days": None,
        "people": None,
        "preferences": [],
        "itinerary": [],
        "ui": {},
        "input_text": "",
    })

    # Merge UI selections into state if provided
    if body.preferences:
        session["preferences"] = [p.strip().lower() for p in body.preferences]

    # Provide the latest user text
    session["messages"].append({"type": "human", "content": body.message})
    session["input_text"] = body.message or ""

    # Invoke the graph
    result = graph.invoke(session)

    # Persist new state
    _SESSIONS[sid] = result

    # Find the latest AI message
    ai_text = ""
    for m in reversed(result.get("messages", [])):
        if getattr(m, "type", None) == "ai" or (isinstance(m, dict) and m.get("type") == "ai"):
            ai_text = m.content if hasattr(m, "content") else m.get("content", "")
            break

    ui = result.get("ui", {}) or {}
    return JSONResponse({"reply": ai_text, "ui": ui})
