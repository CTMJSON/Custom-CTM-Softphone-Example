"""
CTM Softphone Web App — desk mode
----------------------------------
Two-panel layout: CTM phone embed (left) + activity log (right).
Phone embed authenticates via /ctm-phone-access using identity from .env
or a one-time login form.
"""

import base64
import html
import functools
import os
import re
import secrets
import subprocess
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import requests

from flask import (
    Flask, session, request, redirect, url_for,
    render_template, jsonify, Response
)
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

DEFAULT_CTM_API_KEY    = os.environ.get("CTM_API_KEY", "")
DEFAULT_CTM_API_SECRET = os.environ.get("CTM_API_SECRET", "")
DEFAULT_CTM_ACCOUNT_ID = os.environ.get("CTM_ACCOUNT_ID", os.environ.get("DEFAULT_ACCOUNT_ID", ""))
CTM_BASE               = "https://app.calltrackingmetrics.com/api/v1"

# Optional: pre-configure user identity so no login form is needed
DEFAULT_CTM_USER_EMAIL = os.environ.get("CTM_USER_EMAIL", "")
DEFAULT_CTM_USER_FIRST = os.environ.get("CTM_USER_FIRST", "")
DEFAULT_CTM_USER_LAST  = os.environ.get("CTM_USER_LAST", "")
DEFAULT_CTM_CHAT_TOKEN = os.environ.get("CTM_CHAT_TOKEN", "").strip()
APP_TIMEZONE = ZoneInfo("America/New_York")
DEFAULT_CHAT_TOKENS = {
    "11774": "eyJhbGciOiJub25lIn0.eyJyIjoicHJvZHVjdGlvbiIsImkiOjIwOTYsImEiOjExNzc0LCJwIjoiaHR0cHM6IiwiaCI6ImNoYXQuYWN0bS54eXoifQ.",
}
DEFAULT_OPS_WEATHER_CITY = os.environ.get("OPS_WEATHER_CITY", "New York, NY").strip()
DEFAULT_OPS_NEWS_FEED_URL = os.environ.get("OPS_NEWS_FEED_URL", "https://feeds.npr.org/1001/rss.xml").strip()
WEATHER_CODE_LABELS = {
    0: "Clear",
    1: "Mostly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Freezing fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    56: "Freezing drizzle",
    57: "Heavy freezing drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Heavy freezing rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Rain showers",
    81: "Heavy showers",
    82: "Violent showers",
    85: "Snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm and hail",
    99: "Severe thunderstorm",
}


def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        _auto_login()
        if not login_session_ready():
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def _auto_login():
    """If identity is pre-configured in .env, skip the login form."""
    if "email" not in session and DEFAULT_CTM_USER_EMAIL and DEFAULT_CTM_USER_FIRST and DEFAULT_CTM_USER_LAST:
        session["email"]      = DEFAULT_CTM_USER_EMAIL
        session["first_name"] = DEFAULT_CTM_USER_FIRST
        session["last_name"]  = DEFAULT_CTM_USER_LAST
        session["session_id"] = str(uuid.uuid4())
    if "ctm_config" not in session and (DEFAULT_CTM_API_KEY or DEFAULT_CTM_API_SECRET or DEFAULT_CTM_ACCOUNT_ID):
        session["ctm_config"] = {
            "api_key": DEFAULT_CTM_API_KEY,
            "api_secret": DEFAULT_CTM_API_SECRET,
            "account_id": DEFAULT_CTM_ACCOUNT_ID,
            "chat_token": DEFAULT_CTM_CHAT_TOKEN,
            "weather_city": DEFAULT_OPS_WEATHER_CITY,
            "news_feed_url": DEFAULT_OPS_NEWS_FEED_URL,
        }


def get_runtime_config():
    config = extract_mapping(session.get("ctm_config"))
    return {
        "api_key": first_non_empty(config.get("api_key"), DEFAULT_CTM_API_KEY),
        "api_secret": first_non_empty(config.get("api_secret"), DEFAULT_CTM_API_SECRET),
        "account_id": first_non_empty(config.get("account_id"), DEFAULT_CTM_ACCOUNT_ID),
        "chat_token": first_non_empty(config.get("chat_token"), DEFAULT_CTM_CHAT_TOKEN),
        "weather_city": first_non_empty(config.get("weather_city"), DEFAULT_OPS_WEATHER_CITY),
        "news_feed_url": first_non_empty(config.get("news_feed_url"), DEFAULT_OPS_NEWS_FEED_URL),
    }


def get_login_form_defaults():
    config = get_runtime_config()
    return {
        "api_key": config["api_key"],
        "api_secret": config["api_secret"],
        "account_id": config["account_id"],
        "chat_token": config["chat_token"],
        "weather_city": config["weather_city"],
        "news_feed_url": config["news_feed_url"],
        "email": session.get("email", DEFAULT_CTM_USER_EMAIL),
        "first_name": session.get("first_name", DEFAULT_CTM_USER_FIRST),
        "last_name": session.get("last_name", DEFAULT_CTM_USER_LAST),
    }


def login_session_ready():
    config = get_runtime_config()
    return bool(
        session.get("email")
        and session.get("first_name")
        and session.get("last_name")
        and config["api_key"]
        and config["api_secret"]
        and config["account_id"]
    )


def missing_ctm_config():
    config = get_runtime_config()
    missing = []
    if not config["api_key"]:
        missing.append("CTM_API_KEY")
    if not config["api_secret"]:
        missing.append("CTM_API_SECRET")
    if not config["account_id"]:
        missing.append("CTM_ACCOUNT_ID")
    return missing


def config_error_message():
    missing = missing_ctm_config()
    if not missing:
        return None
    return "Missing CTM configuration: " + ", ".join(missing)


def resolve_chat_token(account_id, configured_token):
    token = (configured_token or "").strip()
    if token:
        return token
    return DEFAULT_CHAT_TOKENS.get(str(account_id or "").strip(), "")


def ctm_get(path, params=None):
    config_error = config_error_message()
    if config_error:
        raise RuntimeError(config_error)
    config = get_runtime_config()
    r = requests.get(
        f"{CTM_BASE}{path}",
        params=params,
        auth=(config["api_key"], config["api_secret"]),
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def extract_collection(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []

    for key in ("calls", "messages", "texts", "activities", "items", "results", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            nested = extract_collection(value)
            if nested:
                return nested
    return []


def extract_mapping(value):
    return value if isinstance(value, dict) else {}


def first_non_empty(*values):
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if value:
                return value
            continue
        if value == 0:
            return value
        if value:
            return value
    return ""


def normalize_account_id_input(value):
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.search(r"/accounts/(\d+)", text, re.IGNORECASE) or re.fullmatch(r"(\d+)", text)
    if match:
        return match.group(1)
    return text


def pick_number(*values):
    for value in values:
        if not value:
            continue
        if isinstance(value, (int, float)):
            value = str(int(value))
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
    return ""


def parse_datetime(value):
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).astimezone(APP_TIMEZONE)

    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    for fmt in (
        "%Y-%m-%d %I:%M %p %z",
        "%Y-%m-%d %H:%M:%S %z",
        "%Y-%m-%d %H:%M %z",
        "%Y-%m-%d %I:%M:%S %p %z",
    ):
        try:
            return datetime.strptime(text, fmt).astimezone(APP_TIMEZONE)
        except ValueError:
            continue

    for candidate in (text, text.replace(" ", "T", 1)):
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=APP_TIMEZONE)
            return dt.astimezone(APP_TIMEZONE)
        except ValueError:
            continue
    return None


def format_datetime_parts(value):
    dt = parse_datetime(value)
    if not dt:
        return "Unknown time", "No date"
    return dt.strftime("%-I:%M %p"), dt.strftime("%b %-d")


def datetime_sort_value(value):
    dt = parse_datetime(value)
    if not dt:
        return 0
    return int(dt.timestamp())


def format_duration(value):
    try:
        seconds = int(value or 0)
    except (TypeError, ValueError):
        seconds = 0
    if seconds <= 0:
        return "—"
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def summarize_direction(raw_direction, default_outbound_label="Outbound"):
    direction = str(raw_direction or "").lower()
    if "chat" in direction:
        return "Chat", "chat"
    if any(word in direction for word in ("inbound", "incoming", "received")):
        return "Inbound", "inbound"
    if any(word in direction for word in ("outbound", "outgoing", "sent")):
        return default_outbound_label, "outbound"
    if "sms" in direction or "message" in direction or "text" in direction:
        return "Text", "text"
    return default_outbound_label, "outbound"


def summarize_call_status(raw_status):
    status = str(raw_status or "").strip()
    lowered = status.lower()
    if "answer" in lowered and "no" not in lowered:
        return "Answered", "answered"
    if "miss" in lowered or "abandon" in lowered:
        return "Missed", "missed"
    if "busy" in lowered:
        return "Busy", "busy"
    if "voicemail" in lowered:
        return "Voicemail", "other"
    if "fail" in lowered:
        return "Failed", "other"
    return status.title() if status else "Unknown", "other"


def fetch_collection(paths, params=None):
    last_exc = None
    for path in paths:
        try:
            payload = ctm_get(path, params)
            records = extract_collection(payload)
            if records:
                return payload, records, path
            if path == paths[-1]:
                return payload, records, path
        except Exception as exc:
            last_exc = exc
    if last_exc:
        raise last_exc
    return {}, [], paths[-1]


def normalize_calls(records):
    normalized = []
    for raw in records:
        record = extract_mapping(raw)
        if not record:
            continue

        caller = extract_mapping(record.get("caller"))
        contact = extract_mapping(record.get("contact"))
        agent_obj = extract_mapping(record.get("agent"))

        direction_label, direction_key = summarize_direction(
            first_non_empty(record.get("direction"), record.get("call_type"), record.get("type")),
        )
        if direction_key in {"chat", "text"} or str(record.get("direction") or "").lower().startswith("msg_"):
            continue
        status_label, status_key = summarize_call_status(record.get("status"))

        caller_number = pick_number(
            record.get("caller_number"),
            record.get("caller_phone"),
            caller.get("number"),
            caller.get("phone_number"),
            contact.get("phone_number"),
            record.get("phone_number"),
        )
        dial_number = pick_number(
            record.get("to_number") if direction_key == "outbound" else "",
            caller_number,
            contact.get("phone_number"),
            record.get("phone_number"),
        )
        caller_name = first_non_empty(
            record.get("caller_name"),
            caller.get("name"),
            contact.get("name"),
            contact.get("display_name"),
            caller_number,
            "Unknown caller",
        )
        agent_name = first_non_empty(
            agent_obj.get("name"),
            record.get("agent_name"),
            record.get("answered_by"),
            record.get("user_name"),
        )
        summary = first_non_empty(
            record.get("summary"),
            record.get("ai_summary"),
            record.get("notes"),
            record.get("note"),
            record.get("description"),
        )
        source = first_non_empty(
            record.get("source_name"),
            record.get("utm_source"),
            record.get("source"),
            contact.get("source"),
        )
        raw_time = first_non_empty(record.get("called_at"), record.get("created_at"), record.get("started_at"))
        time_label, date_label = format_datetime_parts(raw_time)
        duration_label = format_duration(first_non_empty(record.get("duration"), record.get("talk_time"), 0))
        callback_priority = 0
        if status_key == "missed":
            callback_priority = 3
        elif direction_key == "inbound":
            callback_priority = 2
        elif direction_key == "outbound":
            callback_priority = 1
        signals = [direction_key, status_key]
        if not summary:
            signals.append("summary-missing")
        if not agent_name:
            signals.append("agent-missing")
        if callback_priority >= 2:
            signals.append("priority-callback")
        search_text = " ".join(
            str(part).lower()
            for part in (
                caller_name,
                caller_number,
                agent_name,
                summary,
                source,
                direction_label,
                status_label,
            )
            if part
        )

        normalized.append(
            {
                "time_label": time_label,
                "date_label": date_label,
                "caller_name": caller_name,
                "caller_number": caller_number,
                "agent_name": agent_name,
                "summary": summary,
                "source": source,
                "direction_label": direction_label,
                "direction_key": direction_key,
                "status_label": status_label,
                "status_key": status_key,
                "duration_label": duration_label,
                "dial_number": dial_number,
                "record_id": str(first_non_empty(record.get("id"), record.get("sid"), uuid.uuid4())),
                "sort_ts": datetime_sort_value(raw_time),
                "callback_priority": callback_priority,
                "signals": signals,
                "search_text": search_text,
            }
        )
    return normalized


def normalize_messages(records):
    normalized = []
    for raw in records:
        record = extract_mapping(raw)
        if not record:
            continue

        message_obj = extract_mapping(record.get("message"))
        contact = extract_mapping(record.get("contact"))
        raw_type = first_non_empty(
            record.get("type"),
            record.get("direction"),
            record.get("message_type"),
            record.get("activity_type"),
            record.get("channel"),
            message_obj.get("type"),
        )
        lowered_type = str(raw_type).lower()
        if lowered_type and not any(token in lowered_type for token in ("sms", "text", "message", "mms", "inbound", "outbound", "sent", "received")):
            continue

        body = first_non_empty(
            record.get("message_body"),
            record.get("body"),
            record.get("message"),
            record.get("content"),
            record.get("text"),
            message_obj.get("body"),
            message_obj.get("content"),
        )
        from_number = pick_number(
            record.get("from_number"),
            record.get("sender"),
            record.get("from"),
            message_obj.get("from_number"),
            message_obj.get("sender"),
            record.get("caller_number"),
            contact.get("phone_number"),
        )
        to_number = pick_number(
            record.get("to_number"),
            record.get("recipient"),
            record.get("to"),
            message_obj.get("to_number"),
            message_obj.get("recipient"),
            record.get("tracking_number"),
            record.get("receiving_number"),
        )
        direction_label, direction_key = summarize_direction(raw_type, default_outbound_label="Outbound")
        if direction_key == "outbound":
            reply_number = to_number or from_number
        else:
            reply_number = from_number or to_number

        contact_name = first_non_empty(
            record.get("contact_name"),
            record.get("name"),
            contact.get("name"),
            contact.get("display_name"),
        )
        status = first_non_empty(record.get("status"), message_obj.get("status"))
        raw_time = first_non_empty(record.get("created_at"), record.get("sent_at"), record.get("updated_at"), record.get("called_at"))
        time_label, date_label = format_datetime_parts(raw_time)
        callback_priority = 2 if direction_key == "inbound" else 1
        signals = [direction_key]
        if not contact_name:
            signals.append("contact-missing")
        if record.get("message_media"):
            signals.append("media")
        if direction_key == "inbound":
            signals.append("priority-reply")
        search_text = " ".join(
            str(part).lower()
            for part in (
                contact_name,
                from_number,
                to_number,
                body,
                status,
                direction_label,
            )
            if part
        )

        normalized.append(
            {
                "time_label": time_label,
                "date_label": date_label,
                "from_number": from_number or "—",
                "to_number": to_number or "—",
                "contact_name": contact_name,
                "body": body,
                "status": status,
                "direction_label": direction_label,
                "direction_key": direction_key,
                "reply_number": reply_number,
                "has_media": bool(record.get("message_media")),
                "record_id": str(first_non_empty(record.get("id"), record.get("message_id"), record.get("sid"), uuid.uuid4())),
                "sort_ts": datetime_sort_value(raw_time),
                "callback_priority": callback_priority,
                "signals": signals,
                "search_text": search_text,
            }
        )
    return normalized


def call_metrics(calls):
    return {
        "Recent Calls": len(calls),
        "Answered": sum(1 for call in calls if call["status_key"] == "answered"),
        "Missed": sum(1 for call in calls if call["status_key"] == "missed"),
        "Outbound": sum(1 for call in calls if call["direction_key"] == "outbound"),
    }


def message_metrics(messages):
    return {
        "Recent Texts": len(messages),
        "Inbound": sum(1 for msg in messages if msg["direction_key"] == "inbound"),
        "Outbound": sum(1 for msg in messages if msg["direction_key"] == "outbound"),
        "With Content": sum(1 for msg in messages if msg["body"]),
    }


def call_focus_cards(calls):
    return [
        {
            "label": "Missed Callbacks",
            "count": sum(1 for call in calls if "missed" in call["signals"]),
            "hint": "Most urgent return calls first.",
            "filter": "missed",
            "sort": "callback",
            "signals": "missed",
        },
        {
            "label": "Unassigned Inbound",
            "count": sum(1 for call in calls if {"inbound", "agent-missing"}.issubset(set(call["signals"]))),
            "hint": "Inbound calls without an assigned agent.",
            "filter": "inbound",
            "sort": "callback",
            "signals": "inbound agent-missing",
        },
        {
            "label": "Needs Notes",
            "count": sum(1 for call in calls if "summary-missing" in call["signals"]),
            "hint": "Calls missing a usable summary.",
            "filter": "all",
            "sort": "newest",
            "signals": "summary-missing",
        },
    ]


def message_focus_cards(messages):
    return [
        {
            "label": "Reply Queue",
            "count": sum(1 for message in messages if "priority-reply" in message["signals"]),
            "hint": "Inbound texts needing follow-up.",
            "filter": "inbound",
            "sort": "callback",
            "signals": "inbound",
        },
        {
            "label": "Media Follow-up",
            "count": sum(1 for message in messages if "media" in message["signals"]),
            "hint": "Texts with attachments or images.",
            "filter": "all",
            "sort": "newest",
            "signals": "media",
        },
        {
            "label": "Unknown Contacts",
            "count": sum(1 for message in messages if "contact-missing" in message["signals"]),
            "hint": "Texts without a mapped contact name.",
            "filter": "all",
            "sort": "callback",
            "signals": "contact-missing",
        },
    ]


def assessment_is_available():
    return os.path.exists(ASSESSMENT_SCRIPT) and os.path.exists(ASSESSMENT_PYTHON)


def status_duration_label(status):
    stats = status.get("stats") or []
    if not stats:
        return "Just updated"
    entry = stats[0] or {}
    minutes = int(entry.get("min") or 0)
    seconds = int(entry.get("sec") or 0)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def normalize_agent(agent):
    status = extract_mapping(agent.get("status"))
    value = str(status.get("value") or "offline").lower()
    accepting = bool(status.get("accept"))
    logged_out = bool(status.get("logged_out"))
    queue_total = int(status.get("queue_total") or 0)
    chatting = int(status.get("chatting") or 0)

    availability = "Offline"
    availability_key = "offline"
    if value == "online" and accepting and not logged_out:
        availability = "Available"
        availability_key = "available"
    elif value in {"outbound", "inbound", "call", "busy"} or queue_total > 0:
        availability = "On Call"
        availability_key = "busy"
    elif chatting > 0 or value == "chat":
        availability = "Chatting"
        availability_key = "chat"
    elif logged_out or value == "offline":
        availability = "Offline"
        availability_key = "offline"
    else:
        availability = value.title() if value else "Offline"
        availability_key = "offline"

    return {
        "name": first_non_empty(agent.get("name"), agent.get("email"), "Unknown agent"),
        "initials": first_non_empty(agent.get("initials"), "?"),
        "email": agent.get("email") or "",
        "availability": availability,
        "availability_key": availability_key,
        "queue_total": queue_total,
        "duration_label": status_duration_label(status),
        "accepting": accepting,
    }


def agent_metrics(agents):
    return {
        "Available": sum(1 for agent in agents if agent["availability_key"] == "available"),
        "Busy": sum(1 for agent in agents if agent["availability_key"] == "busy"),
        "Chatting": sum(1 for agent in agents if agent["availability_key"] == "chat"),
        "Offline": sum(1 for agent in agents if agent["availability_key"] == "offline"),
    }


def fetch_agents():
    payload = ctm_get(f"/accounts/{get_runtime_config()['account_id']}/agents/history.json", {"bypass": "cache"})
    agents = [normalize_agent(agent) for agent in payload.get("agents", [])]
    agents.sort(key=lambda agent: (agent["availability_key"] != "available", agent["availability_key"] == "offline", agent["name"].lower()))
    return agents


def weather_code_label(code):
    try:
        return WEATHER_CODE_LABELS.get(int(code), "Current conditions")
    except (TypeError, ValueError):
        return "Current conditions"


def fetch_weather_snapshot(latitude, longitude, *, location_name, timezone_name="auto"):
    forecast = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,weather_code,wind_speed_10m,is_day",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min",
            "timezone": timezone_name or "auto",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "forecast_days": 1,
        },
        timeout=10,
    )
    forecast.raise_for_status()
    payload = forecast.json()
    current = payload.get("current") or {}
    daily = payload.get("daily") or {}
    temperature = current.get("temperature_2m")
    if temperature is None:
        return None
    return {
        "location": location_name,
        "temperature": round(float(temperature)),
        "condition": weather_code_label(current.get("weather_code")),
        "wind_speed": round(float(current.get("wind_speed_10m") or 0)),
        "high": round(float((daily.get("temperature_2m_max") or [temperature])[0])),
        "low": round(float((daily.get("temperature_2m_min") or [temperature])[0])),
        "is_day": bool(current.get("is_day", 1)),
        "observed_at": current.get("time") or "",
    }


def geocode_weather_city(weather_city):
    if not weather_city:
        return None
    geocode = requests.get(
        f"https://geocoding-api.open-meteo.com/v1/search?name={quote_plus(weather_city)}&count=1&language=en&format=json",
        timeout=10,
    )
    geocode.raise_for_status()
    results = geocode.json().get("results") or []
    if not results:
        return None
    place = results[0]
    return {
        "location": ", ".join(part for part in [place.get("name"), place.get("admin1")] if part),
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "timezone": place.get("timezone") or "auto",
    }


def fetch_weather_brief():
    weather_city = get_runtime_config()["weather_city"]
    if not weather_city:
        return None
    try:
        place = geocode_weather_city(weather_city)
        if not place:
            return None
        snapshot = fetch_weather_snapshot(
            place["latitude"],
            place["longitude"],
            location_name=place["location"],
            timezone_name=place["timezone"],
        )
        if not snapshot:
            return None
        return {
            "label": f"Weather {snapshot['location']}",
            "detail": f"{snapshot['temperature']}F, {snapshot['condition']}, wind {snapshot['wind_speed']} mph",
        }
    except Exception:
        return None


def fetch_local_weather_snapshot():
    try:
        location_response = requests.get("https://ipwho.is/", timeout=10)
        location_response.raise_for_status()
        location = location_response.json()
        if location.get("success"):
            snapshot = fetch_weather_snapshot(
                location.get("latitude"),
                location.get("longitude"),
                location_name=", ".join(
                    part for part in [location.get("city"), location.get("region")] if part
                ) or (location.get("country") or "Your area"),
                timezone_name=((location.get("timezone") or {}).get("id") if isinstance(location.get("timezone"), dict) else None) or "auto",
            )
            if snapshot:
                snapshot["source"] = "ip"
                return snapshot
    except Exception:
        pass

    weather_city = get_runtime_config()["weather_city"]
    if not weather_city:
        return None
    try:
        place = geocode_weather_city(weather_city)
        if not place:
            return None
        snapshot = fetch_weather_snapshot(
            place["latitude"],
            place["longitude"],
            location_name=place["location"],
            timezone_name=place["timezone"],
        )
        if snapshot:
            snapshot["source"] = "fallback"
        return snapshot
    except Exception:
        return None


def _parse_news_feed(news_feed_url, limit=20, lookback_hours=72):
    if not news_feed_url:
        return []
    try:
        response = requests.get(news_feed_url, timeout=10)
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
        cutoff = datetime.now(APP_TIMEZONE) - timedelta(hours=lookback_hours)
        parsed_items = []
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            link = (item.findtext("link") or "").strip()
            if not title:
                continue
            try:
                published_dt = parsedate_to_datetime(pub_date).astimezone(APP_TIMEZONE)
            except Exception:
                published_dt = None
            parsed_items.append((published_dt, html.unescape(title), link))

        def format_item(published_dt, title, link):
            if published_dt:
                if published_dt.date() == datetime.now(APP_TIMEZONE).date():
                    published = published_dt.strftime("%-I:%M %p")
                else:
                    published = published_dt.strftime("%a %-I:%M %p")
            else:
                published = "Latest"
            return {"label": published, "detail": title, "link": link}

        recent_items = [
            format_item(published_dt, title, link)
            for published_dt, title, link in parsed_items
            if published_dt is None or published_dt >= cutoff
        ][:limit]
        if recent_items:
            return recent_items

        return [format_item(published_dt, title, link) for published_dt, title, link in parsed_items[:limit]]
    except Exception:
        return []


def fetch_news_briefs(limit=20, lookback_hours=72):
    configured_feed_url = get_runtime_config()["news_feed_url"]
    preferred_urls = []
    if configured_feed_url:
        preferred_urls.append(configured_feed_url)
    if DEFAULT_OPS_NEWS_FEED_URL and DEFAULT_OPS_NEWS_FEED_URL not in preferred_urls:
        preferred_urls.append(DEFAULT_OPS_NEWS_FEED_URL)

    for news_feed_url in preferred_urls:
        items = _parse_news_feed(news_feed_url, limit=limit, lookback_hours=lookback_hours)
        if items:
            return items
    return []


def build_ops_items():
    items = []
    items.extend(fetch_news_briefs())
    if not items:
        items.append({"label": "Latest", "detail": "No recent stories are available from the configured feed right now."})
    return items


# ── Pages ────────────────────────────────────────────────────────────────────

@app.get("/login")
def login():
    _auto_login()
    if login_session_ready():
        return redirect(url_for("index"))
    return render_template("login.html", error=None, form_data=get_login_form_defaults())


@app.post("/login")
def login_post():
    api_key    = request.form.get("api_key", "").strip()
    api_secret = request.form.get("api_secret", "").strip()
    account_id = normalize_account_id_input(request.form.get("account_id", ""))
    email      = request.form.get("email", "").strip()
    first_name = request.form.get("first_name", "").strip()
    last_name  = request.form.get("last_name", "").strip()
    chat_token = request.form.get("chat_token", "").strip()
    weather_city = request.form.get("weather_city", "").strip() or DEFAULT_OPS_WEATHER_CITY
    news_feed_url = request.form.get("news_feed_url", "").strip() or DEFAULT_OPS_NEWS_FEED_URL
    form_data = {
        "api_key": api_key,
        "api_secret": api_secret,
        "account_id": account_id,
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
        "chat_token": chat_token,
        "weather_city": weather_city,
        "news_feed_url": news_feed_url,
    }
    if not all([api_key, api_secret, account_id, email, first_name, last_name]):
        return render_template("login.html", error="API key, API secret, account ID, and agent identity are required.", form_data=form_data)
    session.clear()
    session["ctm_config"] = {
        "api_key": api_key,
        "api_secret": api_secret,
        "account_id": account_id,
        "chat_token": chat_token,
        "weather_city": weather_city,
        "news_feed_url": news_feed_url,
    }
    session["email"]      = email
    session["first_name"] = first_name
    session["last_name"]  = last_name
    session["session_id"] = str(uuid.uuid4())
    return redirect(url_for("index"))


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
@login_required
def index():
    config = get_runtime_config()
    return render_template(
        "phone.html",
        user_name=f"{session['first_name']} {session['last_name']}",
        account_id=config["account_id"],
        chat_token=resolve_chat_token(config["account_id"], config["chat_token"]),
        assessment_available=assessment_is_available(),
    )


# ── Phone embed auth ─────────────────────────────────────────────────────────

@app.post("/ctm-phone-access")
@login_required
def ctm_phone_access():
    config_error = config_error_message()
    if config_error:
        return jsonify({"status": "error", "message": config_error}), 400
    config = get_runtime_config()

    payload = {
        "email":      session["email"],
        "first_name": session["first_name"],
        "last_name":  session["last_name"],
        "session_id": session["session_id"],
    }
    try:
        r = requests.post(
            f"{CTM_BASE}/accounts/{config['account_id']}/phone_access",
            json=payload,
            auth=(config["api_key"], config["api_secret"]),
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as exc:
        app.logger.error("CTM phone_access error: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 502

    data.update({
        "sessionId":  session["session_id"],
        "email":      session["email"],
        "first_name": session["first_name"],
        "last_name":  session["last_name"],
        "session_id": session["session_id"],
    })
    return jsonify(data)


@app.post("/ctm-phone-refresh")
@login_required
def ctm_phone_refresh():
    return ctm_phone_access()


# ── Data proxies ─────────────────────────────────────────────────────────────

@app.get("/ctm/calls")
@login_required
def ctm_calls():
    config = get_runtime_config()
    try:
        _, records, _ = fetch_collection([f"/accounts/{config['account_id']}/calls.json"], {"per_page": 75})
        calls = normalize_calls(records)
        error = None
    except Exception as exc:
        calls, error = [], str(exc)
    return render_template(
        "data/calls.html",
        calls=calls,
        error=error,
        metrics=call_metrics(calls),
        focus_cards=call_focus_cards(calls),
        updated_at=datetime.now().strftime("%-I:%M %p"),
    )


@app.get("/ctm/messages")
@login_required
def ctm_messages():
    config = get_runtime_config()
    try:
        _, records, _ = fetch_collection(
            [
                f"/accounts/{config['account_id']}/calls.json",
                f"/accounts/{config['account_id']}/messages.json",
                f"/accounts/{config['account_id']}/texts.json",
                f"/accounts/{config['account_id']}/activities.json",
            ],
            {
                "per_page": 75,
                "direction[]": ["msg_inbound", "msg_outbound"],
            },
        )
        messages = normalize_messages(records)
        error = None
    except Exception as exc:
        messages, error = [], str(exc)
    return render_template(
        "data/messages.html",
        messages=messages,
        error=error,
        metrics=message_metrics(messages),
        focus_cards=message_focus_cards(messages),
        updated_at=datetime.now().strftime("%-I:%M %p"),
    )


@app.get("/ctm/ops-panel")
@login_required
def ctm_ops_panel():
    try:
        agents = fetch_agents()
        error = None
    except Exception as exc:
        agents = []
        error = str(exc)
    return render_template(
        "data/ops_panel.html",
        agents=agents,
        metrics=agent_metrics(agents),
        error=error,
        updated_at=datetime.now().strftime("%-I:%M %p"),
    )


@app.get("/ctm/ops-feed")
@login_required
def ctm_ops_feed():
    return render_template(
        "data/ops_feed.html",
        feed_items=build_ops_items(),
        updated_at=datetime.now().strftime("%-I:%M %p"),
    )


@app.get("/ctm/local-weather")
@login_required
def ctm_local_weather():
    snapshot = fetch_local_weather_snapshot()
    if not snapshot:
        return jsonify({"status": "error", "message": "Weather unavailable"}), 502
    return jsonify({
        "status": "ok",
        "location": snapshot["location"],
        "temperature": snapshot["temperature"],
        "condition": snapshot["condition"],
        "wind_speed": snapshot["wind_speed"],
        "high": snapshot["high"],
        "low": snapshot["low"],
        "is_day": snapshot["is_day"],
        "observed_at": snapshot["observed_at"],
        "source": snapshot.get("source", "ip"),
    })


# ── Account Assessment ───────────────────────────────────────────────────────

ASSESSMENT_SCRIPT = os.path.expanduser(
    os.environ.get(
        "CTM_ASSESSMENT_SCRIPT",
        "~/Scripts/ctm-account-assessment/src/ctm_account_asses.py",
    )
)
ASSESSMENT_PYTHON = os.path.expanduser(
    os.environ.get(
        "CTM_ASSESSMENT_PYTHON",
        "~/Scripts/ctm-account-assessment/venv/bin/python",
    )
)

@app.get("/assessment")
@login_required
def assessment():
    """Run the CTM account assessment and stream the HTML report back."""
    if not assessment_is_available():
        return Response(
            "<p style='color:red;padding:20px'>Assessment tooling is not configured on this machine.</p>",
            mimetype="text/html",
        )
    config = get_runtime_config()

    # The assessment script sends Authorization: Basic <value> directly,
    # so it needs the standard base64(key:secret) encoding.
    basic_token = base64.b64encode(
        f"{config['api_key']}:{config['api_secret']}".encode()
    ).decode()

    def generate():
        yield "<p style='padding:20px;font-family:sans-serif'>⏳ Running account assessment — this takes ~30–60 seconds…</p>"

        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                result = subprocess.run(
                    [
                        ASSESSMENT_PYTHON,
                        ASSESSMENT_SCRIPT,
                        "--account-id", config["account_id"],
                        "--api-key",    basic_token,
                        "--out-dir",    tmpdir,
                        "--calls-limit","200",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
            except subprocess.TimeoutExpired:
                yield "<p style='color:red;padding:20px'>Assessment timed out after 3 minutes.</p>"
                return
            except Exception as exc:
                yield f"<p style='color:red;padding:20px'>Error running assessment: {exc}</p>"
                return

            if result.returncode != 0:
                yield (
                    f"<p style='color:red;padding:20px'>Assessment failed:<br>"
                    f"<pre>{result.stderr[:2000]}</pre></p>"
                )
                return

            html_path = os.path.join(
                tmpdir, f"ctm_account_assessment_{config['account_id']}.html"
            )
            if not os.path.exists(html_path):
                yield "<p style='color:red;padding:20px'>Assessment ran but no HTML file was produced.</p>"
                return

            with open(html_path, encoding="utf-8") as f:
                yield f.read()

    return Response(generate(), mimetype="text/html")


# ── Run ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port  = int(os.environ.get("PORT", 8080))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
