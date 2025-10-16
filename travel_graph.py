# graph/travel_graph.py
from __future__ import annotations

import operator
import re
from typing import Annotated, List, Optional, TypedDict

from langgraph.graph import StateGraph, END
from langchain_core.messages import AIMessage

from agents.itinerary_agent import plan_trip

# Helpers
_NUM_RE = re.compile(r"(\d+)")


def _extract_numbers(text: str) -> List[int]:
    return [int(x) for x in _NUM_RE.findall(text or "")]


# Dialog state schema
class TravelState(TypedDict, total=False):
    messages: Annotated[List, operator.add]  # chat transcript
    input_text: str  # latest user text
    ui: dict  # UI hints for front-end

    name: Optional[str]
    destination: Optional[str]
    days: Optional[int]
    people: Optional[int]
    start_date: Optional[str]  # New slot to collect start date YYYY-MM-DD
    preferences: List[str]
    itinerary: List[str]


def travel_node(state: TravelState) -> TravelState:
    messages = state.get("messages", [])
    user_text = (state.get("input_text") or "").strip()

    name = state.get("name")
    dest = state.get("destination")
    days = state.get("days")
    people = state.get("people")
    start_date = state.get("start_date")
    prefs = state.get("preferences", [])

    # 1) Name
    if not name:
        if user_text:
            name = user_text.title()
            ai = AIMessage(content=f"Hi {name}, where are you planning to go on a trip?")
            return {"messages": messages + [ai], "name": name}
        return {"messages": messages + [AIMessage(content="Hi, please state your name.")]}

    # 2) Destination
    if not dest:
        if user_text:
            dest = user_text.strip().title()
            opening = f"Wow, {dest} is a nice place."
            ai = AIMessage(content=f"{opening} How many days and people are going on the trip?")
            return {"messages": messages + [ai], "destination": dest}
        return {"messages": messages + [AIMessage(content="Please tell the destination city or place.")]}

    # 3) Days & People
    if not days or not people:
        if user_text:
            nums = _extract_numbers(user_text)
            if len(nums) >= 2:
                days, people = nums[0], nums[1]
            elif len(nums) == 1 and not days:
                days = nums[0]
            elif len(nums) == 1 and not people:
                people = nums[0]

        if not days or not people:
            ai = AIMessage(content="Please specify trip length and group size, e.g., '5 days and 2 people'.")
            return {"messages": messages + [ai]}

        ai = AIMessage(content="Great. What is the trip start date? Please provide in YYYY-MM-DD format.")
        return {"messages": messages + [ai], "days": days, "people": people}

    # 4) Start Date
    if not start_date:
        if user_text:
            start_date = user_text.strip()
            # Proceed to preferences prompt + save start_date
            ui_hint = {
                "type": "preferences",
                "options": [
                    "nightlife", "food", "shopping", "historical places",
                    "natural places", "street life", "famous places"
                ],
            }
            ai = AIMessage(content="One last thing—select preferences from the checkboxes, then send.")
            return {"messages": messages + [ai], "start_date": start_date, "ui": ui_hint}
        ai = AIMessage(content="Please provide the trip start date in YYYY-MM-DD format.")
        return {"messages": messages + [ai]}

    # 5) Preferences
    if not prefs:
        chosen = [x.strip().lower() for x in user_text.split(",") if x.strip()] if user_text else []
        if not chosen:
            ui_hint = {
                "type": "preferences",
                "options": [
                    "nightlife", "food", "shopping", "historical places",
                    "natural places", "street life", "famous places"
                ],
            }
            ai = AIMessage(content="Please select your preferences using the checkboxes.")
            return {"messages": messages + [ai], "ui": ui_hint}
        prefs = chosen

    # 6) Plan itinerary
    opening, itinerary = plan_trip(dest, days, people, prefs, start_date)
    ai = AIMessage(content="\n".join(["That's great—planning your itinerary now.", opening] + itinerary))
    return {"messages": messages + [ai], "preferences": prefs, "itinerary": itinerary, "ui": {}}


# Build graph
def build_graph():
    builder = StateGraph(TravelState)
    builder.add_node("travel", travel_node)
    builder.set_entry_point("travel")
    builder.add_edge("travel", END)
    return builder.compile()
