# agents/itinerary_agent.py
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional, Tuple
import os
import random
import requests

from dotenv import load_dotenv
load_dotenv()

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
HF_TOKEN = os.getenv("HUGGINGFACE_API_KEY", "")

# -------- Optional HF fun fact --------
try:
    from huggingface_hub import InferenceClient
    _hf_client = InferenceClient(token=HF_TOKEN) if HF_TOKEN else None
except Exception:
    _hf_client = None

# ---------- Static fallback fun facts ----------
_FUN_FACTS: Dict[str, List[str]] = {
    "goa": [
        "Goa was under Portuguese rule for more than four centuries until 1961.",
        "The Basilica of Bom Jesus in Old Goa is a UNESCO World Heritage Site.",
        "Goa’s coastline spans about 100 km with beaches like Baga and Calangute."
    ],
}

def fun_fact(place: str) -> str:
    # Try HF first
    if _hf_client:
        prompt = (
            f"Give one short, accurate fun fact about {place} for travelers. "
            f"One sentence only, no emojis."
        )
        try:
            text = _hf_client.text_generation(
                prompt,
                max_new_tokens=50,
                temperature=0.7,
            )
            if isinstance(text, str) and text.strip():
                return text.strip()
        except Exception:
            pass
    # Fallback
    key = place.strip().lower()
    if key in _FUN_FACTS:
        return random.choice(_FUN_FACTS[key])
    return f"{place.title()} has a rich culture and popular local spots worth exploring."

# ---------- OpenWeather geocoding ----------
def geocode(place: str) -> Optional[Tuple[float, float]]:
    """
    Resolve (lat, lon) via OpenWeather Direct Geocoding.
    """
    if not OPENWEATHER_API_KEY:
        return None
    url = "https://api.openweathermap.org/geo/1.0/direct"
    params = {"q": place, "limit": 1, "appid": OPENWEATHER_API_KEY}
    r = requests.get(url, params=params, timeout=10)
    if r.status_code != 200:
        return None
    data = r.json() or []
    if not data:
        return None
    top = data[0]
    return float(top["lat"]), float(top["lon"])

# ---------- OpenWeather forecasts ----------
def _onecall_daily(lat: float, lon: float, days: int) -> Optional[List[dict]]:
    """
    Try One Call 3.0 daily forecast (up to 8 days).
    """
    url = "https://api.openweathermap.org/data/3.0/onecall"
    params = {
        "lat": lat,
        "lon": lon,
        "exclude": "minutely",
        "units": "metric",
        "appid": OPENWEATHER_API_KEY,
    }
    r = requests.get(url, params=params, timeout=10)
    if r.status_code != 200:
        return None
    payload = r.json() or {}
    daily = payload.get("daily") or []
    out = []
    for d in daily[:days]:
        # dt is Unix UTC; temp has min/max in metric when units=metric
        date = dt.datetime.utcfromtimestamp(d["dt"]).strftime("%Y-%m-%d")
        t_min = d.get("temp", {}).get("min")
        t_max = d.get("temp", {}).get("max")
        pop = d.get("pop")  # 0..1
        out.append({
            "date": date,
            "t_min": t_min,
            "t_max": t_max,
            "precip_prob": int(round((pop or 0) * 100)),
        })
    return out[:days] if out else None

def _forecast5_aggregate(lat: float, lon: float, days: int) -> List[dict]:
    """
    Aggregate 5 day / 3 hour forecast into daily summaries.
    """
    url = "https://api.openweathermap.org/data/2.5/forecast"
    params = {"lat": lat, "lon": lon, "units": "metric", "appid": OPENWEATHER_API_KEY}
    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    by_day: Dict[str, dict] = {}
    for item in data.get("list", []):
        dt_txt = item.get("dt_txt")  # 'YYYY-MM-DD HH:MM:SS'
        if not dt_txt:
            continue
        day_key = dt_txt.split(" ")[0]
        main = item.get("main", {})
        t = main.get("temp")
        t_min = main.get("temp_min")
        t_max = main.get("temp_max")
        pop = item.get("pop", 0)  # 0..1
        b = by_day.setdefault(day_key, {"temps": [], "mins": [], "maxs": [], "pops": []})
        if t is not None: b["temps"].append(t)
        if t_min is not None: b["mins"].append(t_min)
        if t_max is not None: b["maxs"].append(t_max)
        b["pops"].append(pop)
    out = []
    for day in sorted(by_day.keys())[:days]:
        b = by_day[day]
        tmin = min(b["mins"]) if b["mins"] else (min(b["temps"]) if b["temps"] else None)
        tmax = max(b["maxs"]) if b["maxs"] else (max(b["temps"]) if b["temps"] else None)
        pop_pct = int(round(max(b["pops"]) * 100)) if b["pops"] else 0
        out.append({"date": day, "t_min": tmin, "t_max": tmax, "precip_prob": pop_pct})
    return out[:days]

def daily_weather(lat: float, lon: float, days: int, start_date: Optional[str] = None) -> List[dict]:
    ...

    """
    Prefer One Call 3.0 daily; fall back to 5-day/3-hour aggregation.
    """
    if not OPENWEATHER_API_KEY:
        return []
    oc = _onecall_daily(lat, lon, days)
    if oc:
        if start_date:
            sd = dt.date.fromisoformat(start_date)
            idx = next((i for i, d in enumerate(oc) if dt.date.fromisoformat(d["date"]) >= sd), 0)
            return oc[idx: idx + days]
        else:
            return oc
    forecast5 = _forecast5_aggregate(lat, lon, days)
    if start_date:
        sd = dt.date.fromisoformat(start_date)
        idx = next((i for i, d in enumerate(forecast5) if dt.date.fromisoformat(d["date"]) >= sd), 0)
        return forecast5[idx: idx + days]
    else:
        return forecast5
    #return _forecast5_aggregate(lat, lon, days)

# ---------- Itinerary generator ----------
_ACTIVITY_MAP = {
    "nightlife": ["evening at a popular club area", "sunset beach shacks", "live music venue"],
    "food": ["local seafood lunch", "street food crawl", "heritage café tasting"],
    "shopping": ["local market for handicrafts", "flea market visit", "souvenir boutiques"],
    "historical places": ["old town walking tour", "heritage church/fort visit", "museum hour"],
    "natural places": ["beach and coastline walk", "nature trail / waterfall", "sunrise viewpoint"],
    "street life": ["promenade stroll", "photo walk", "local square hangout"],
    "famous places": ["top landmarks circuit", "iconic photo spots", "must-see square/fort"],
}

def build_itinerary(destination: str, days: int, people: int, preferences: List[str], weather: List[dict]) -> List[str]:
    prefs = [p.lower() for p in preferences]
    pool: List[str] = []
    for p in prefs:
        pool.extend(_ACTIVITY_MAP.get(p, []))
    if not pool:
        pool = ["city highlights tour", "local food tasting", "market visit", "sunset viewpoint"]

    plan = []
    for i in range(days):
        slot = pool[i % len(pool)]
        w = weather[i] if i < len(weather) else None
        if w and w.get("t_min") is not None and w.get("t_max") is not None:
            avg = int(round((w["t_min"] + w["t_max"]) / 2))
            tip = f"weather is ~{avg}°C with rain chance {w.get('precip_prob', 0)}%"
        else:
            tip = "weather details unavailable"
        plan.append(f"Day {i+1}: {slot} in {destination.title()} — {tip}.")
    if plan:
        plan[-1] += f" Departure planning for {people} traveler(s)."
    return plan

def plan_trip(destination: str, days: int, people: int, preferences: List[str], start_date: Optional[str] = None) -> Tuple[str, List[str]]:
    fact = fun_fact(destination)
    coords = geocode(destination)
    weather_list: List[dict] = []
    if coords:
        lat, lon = coords
        weather_list = daily_weather(lat, lon, days, start_date)  # pass start_date here
    itinerary = build_itinerary(destination, days, people, preferences, weather_list)
    opening = f"Wow, {destination.title()} is a nice place — fun fact: {fact}"
    return opening, itinerary


