#!/usr/bin/env python3
"""
OpenClaw Agent Management Dashboard
------------------------------------
A web dashboard for monitoring OpenClaw agents, tracking usage,
managing tasks via Kanban, and viewing request logs.

Configuration is driven entirely by environment variables (see .env.example).
Defaults assume a standard ~/.openclaw installation.
"""

import json
import os
import glob
import uuid
import resource
import shutil
import time
import requests as http_requests
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, request, render_template

# Load .env file if present (silently skipped if python-dotenv not installed)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Configuration — all values come from environment variables with defaults
# ---------------------------------------------------------------------------

BASE_DIR = os.path.expanduser(os.environ.get("OPENCLAW_BASE_DIR", "~/.openclaw"))

AGENTS_DIR      = os.environ.get("OPENCLAW_AGENTS_DIR",    os.path.join(BASE_DIR, "agents"))
WORKSPACE_DIR   = os.environ.get("OPENCLAW_WORKSPACE_DIR", os.path.join(BASE_DIR, "workspace"))
CONFIG_PATH     = os.environ.get("OPENCLAW_CONFIG_PATH",   os.path.join(BASE_DIR, "openclaw.json"))
GATEWAY_TOKEN   = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "")
PORT            = int(os.environ.get("DASHBOARD_PORT", 5050))
HOST            = os.environ.get("DASHBOARD_HOST", "0.0.0.0")

# openclaw binary — auto-discovered via PATH, or override with OPENCLAW_BIN
OPENCLAW_BIN = os.environ.get("OPENCLAW_BIN", shutil.which("openclaw") or "/usr/local/bin/openclaw")

# Runtime data files (live next to app.py)
KANBAN_PATH     = os.path.join(os.path.dirname(__file__), "kanban.json")
RATE_LIMIT_FILE = os.path.join(os.path.dirname(__file__), "rate_limits.json")

# ---------------------------------------------------------------------------
# Agent color palette — colors are assigned deterministically by agent name
# so new agents always get a consistent color without any configuration
# ---------------------------------------------------------------------------

AGENT_COLOR_PALETTE = [
    "#6366f1",  # indigo
    "#10b981",  # emerald
    "#f59e0b",  # amber
    "#ef4444",  # red
    "#8b5cf6",  # violet
    "#06b6d4",  # cyan
    "#f97316",  # orange
    "#84cc16",  # lime
    "#ec4899",  # pink
    "#14b8a6",  # teal
]


def get_agent_color(agent_id: str) -> str:
    """Return a stable color for an agent based on its name."""
    idx = sum(ord(c) for c in agent_id) % len(AGENT_COLOR_PALETTE)
    return AGENT_COLOR_PALETTE[idx]


# ---------------------------------------------------------------------------
# Model metadata — used for rate limit window calculations
# ---------------------------------------------------------------------------

MODEL_META = {
    "anthropic/claude-sonnet-4-6": {
        "label": "Claude Sonnet 4.6",
        "subscription": "Claude Pro ($20/mo)",
        "reset_minutes": 245,
        "note": "Personal Pro plan — not API billing",
    },
    "anthropic/claude-opus-4-6": {
        "label": "Claude Opus 4.6",
        "subscription": "Claude Pro ($20/mo)",
        "reset_minutes": 245,
        "note": "Personal Pro plan — not API billing",
    },
    "anthropic/main": {
        "label": "Claude (Pro Plan)",
        "subscription": "Claude Pro ($20/mo)",
        "reset_minutes": 245,
        "note": "Maps to Claude Pro subscription",
    },
}

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.secret_key = os.environ.get("DASHBOARD_SECRET_KEY", "openclaw-dashboard")

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def load_rate_limits() -> dict:
    if os.path.exists(RATE_LIMIT_FILE):
        with open(RATE_LIMIT_FILE) as f:
            return json.load(f)
    return {"providers": {}}


def save_rate_limits(data: dict) -> None:
    with open(RATE_LIMIT_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_config() -> dict:
    """Load openclaw.json — returns empty dict if not found."""
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def discover_agent_ids() -> list[str]:
    """Auto-discover agents by scanning AGENTS_DIR for subdirectories."""
    if not os.path.isdir(AGENTS_DIR):
        return []
    agents = []
    for entry in os.scandir(AGENTS_DIR):
        if entry.is_dir():
            agents.append(entry.name)
    return sorted(agents)


def get_default_model() -> str:
    """Read the default model from openclaw.json config."""
    try:
        cfg = load_config()
        m = cfg.get("agents", {}).get("defaults", {}).get("model", {})
        if isinstance(m, dict):
            return m.get("primary", "unknown")
        return m or "unknown"
    except Exception:
        return "unknown"


def get_agent_channel_info(aid: str) -> tuple[str, str]:
    """
    Infer channel/accountId for an agent.
    Tries config bindings first, then falls back to sessions.json.
    """
    try:
        cfg = load_config()
        for b in cfg.get("bindings", []):
            if b.get("agentId") == aid:
                match = b.get("match", {})
                return match.get("channel", "—"), match.get("accountId", "—")
    except Exception:
        pass

    sessions_json = os.path.join(AGENTS_DIR, aid, "sessions", "sessions.json")
    if os.path.exists(sessions_json):
        try:
            with open(sessions_json) as f:
                data = json.load(f)
            if isinstance(data, list) and data:
                parts = data[-1].get("key", "").split(":")
                if len(parts) >= 3:
                    return parts[2], "—"
        except Exception:
            pass

    return "—", "—"


def get_openrouter_key() -> str | None:
    """
    Resolve an OpenRouter API key using a priority chain:
    1. OPENCLAW_OPENROUTER_API_KEY env var
    2. Scan all agent auth-profiles.json files for openrouter:default
    """
    # Priority 1: explicit env var
    env_key = os.environ.get("OPENCLAW_OPENROUTER_API_KEY", "").strip()
    if env_key:
        return env_key

    # Priority 2: scan agent directories
    pattern = os.path.join(AGENTS_DIR, "*/agent/auth-profiles.json")
    for profiles_path in glob.glob(pattern):
        try:
            with open(profiles_path) as f:
                profiles = json.load(f).get("profiles", {})
            p = profiles.get("openrouter:default", {})
            key = p.get("apiKey") or p.get("key")
            if key:
                return key
        except Exception:
            continue

    return None


# ---------------------------------------------------------------------------
# Data aggregation
# ---------------------------------------------------------------------------


def get_agents() -> list[dict]:
    """Build agent list with metadata for the Agents panel."""
    default_model = get_default_model()
    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)

    result = []
    for aid in discover_agent_ids():
        channel, account_id = get_agent_channel_info(aid)
        sessions = glob.glob(os.path.join(AGENTS_DIR, aid, "sessions", "*.jsonl"))
        last_active = None
        active_count = 0
        session_mtimes = []

        for s in sessions:
            try:
                mt = os.path.getmtime(s)
                session_mtimes.append(mt)
                ts = datetime.fromtimestamp(mt, tz=timezone.utc)
                if ts > cutoff_24h:
                    active_count += 1
            except Exception:
                pass

        if session_mtimes:
            last_active = datetime.fromtimestamp(
                max(session_mtimes), tz=timezone.utc
            ).isoformat()

        session_mtimes.sort(reverse=True)
        last_3 = [
            datetime.fromtimestamp(t, tz=timezone.utc).isoformat()
            for t in session_mtimes[:3]
        ]

        result.append({
            "id": aid,
            "model": default_model,
            "channel": channel,
            "accountId": account_id,
            "color": get_agent_color(aid),
            "sessionCount": len(sessions),
            "activeSessionCount": active_count,
            "totalSessionCount": len(sessions),
            "lastSessionTimestamps": last_3,
            "lastActive": last_active,
        })
    return result


def parse_usage() -> dict:
    """Parse all session JSONL files and aggregate usage statistics."""
    totals = {
        "input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0,
        "cost": 0.0, "openrouterCost": 0.0, "proPlanCost": 0.0,
    }
    by_model: dict = {}
    timeline: list = []
    by_agent: dict = {}
    cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)

    for agent_dir in glob.glob(os.path.join(AGENTS_DIR, "*")):
        agent_id = os.path.basename(agent_dir)
        agent_totals = {"input": 0, "output": 0, "cost": 0.0}

        for jsonl in glob.glob(os.path.join(agent_dir, "sessions", "*.jsonl")):
            try:
                with open(jsonl) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if rec.get("type") != "message":
                            continue
                        msg = rec.get("message", {})
                        if msg.get("role") != "assistant":
                            continue
                        usage = msg.get("usage", {})
                        if not usage:
                            continue

                        inp  = usage.get("input", 0) or 0
                        out  = usage.get("output", 0) or 0
                        cr   = usage.get("cacheRead", 0) or 0
                        cw   = usage.get("cacheWrite", 0) or 0
                        cost_obj = usage.get("cost", {})
                        cost = (cost_obj.get("total", 0) if isinstance(cost_obj, dict) else 0) or 0
                        provider = msg.get("provider", "unknown")

                        totals["input"]      += inp
                        totals["output"]     += out
                        totals["cacheRead"]  += cr
                        totals["cacheWrite"] += cw
                        totals["cost"]       += cost
                        if provider == "anthropic":
                            totals["proPlanCost"] += cost
                        else:
                            totals["openrouterCost"] += cost

                        agent_totals["input"]  += inp
                        agent_totals["output"] += out
                        agent_totals["cost"]   += cost

                        model = msg.get("model", "unknown")
                        model_key = (
                            f"{provider}/{model}"
                            if provider not in ("unknown", "openclaw")
                            else model
                        )
                        if model_key not in by_model:
                            by_model[model_key] = {
                                "input": 0, "output": 0, "cost": 0.0,
                                "calls": 0, "provider": provider,
                            }
                        by_model[model_key]["input"]  += inp
                        by_model[model_key]["output"] += out
                        by_model[model_key]["cost"]   += cost
                        by_model[model_key]["calls"]  += 1

                        ts_str = rec.get("timestamp") or msg.get("timestamp")
                        if ts_str:
                            try:
                                if isinstance(ts_str, (int, float)):
                                    ts = datetime.fromtimestamp(ts_str / 1000, tz=timezone.utc)
                                else:
                                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                                if ts >= cutoff_24h:
                                    timeline.append({
                                        "timestamp": ts.isoformat(),
                                        "input": inp, "output": out,
                                        "cost": cost, "agent": agent_id,
                                    })
                            except Exception:
                                pass
            except Exception:
                continue

        by_agent[agent_id] = agent_totals

    timeline.sort(key=lambda x: x["timestamp"])
    return {
        "totals": totals,
        "byModel": by_model,
        "byAgent": by_agent,
        "timeline": timeline,
    }


def compute_anthropic_window() -> dict:
    """Compute Anthropic Pro usage within the current rolling rate-limit window."""
    reset_minutes = 245  # default Claude Pro window
    # Try to find the reset_minutes from known model metadata
    for meta in MODEL_META.values():
        reset_minutes = meta.get("reset_minutes", reset_minutes)
        break

    window_start = datetime.now(timezone.utc) - timedelta(minutes=reset_minutes)
    usage = {
        "input": 0, "output": 0, "requests": 0,
        "cache_read": 0, "cache_write": 0,
    }
    oldest_msg_time = None
    newest_msg_time = None

    for agent_dir in glob.glob(os.path.join(AGENTS_DIR, "*")):
        for jsonl in glob.glob(os.path.join(agent_dir, "sessions", "*.jsonl")):
            try:
                with open(jsonl) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if rec.get("type") != "message":
                            continue
                        msg = rec.get("message", {})
                        if msg.get("role") != "assistant" or msg.get("provider") != "anthropic":
                            continue
                        ts_str = rec.get("timestamp") or msg.get("timestamp")
                        if not ts_str:
                            continue
                        try:
                            if isinstance(ts_str, (int, float)):
                                ts = datetime.fromtimestamp(ts_str / 1000, tz=timezone.utc)
                            else:
                                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        except Exception:
                            continue
                        if ts < window_start:
                            continue
                        u = msg.get("usage", {})
                        usage["input"]       += u.get("input", 0) or 0
                        usage["output"]      += u.get("output", 0) or 0
                        usage["cache_read"]  += u.get("cacheRead", 0) or 0
                        usage["cache_write"] += u.get("cacheWrite", 0) or 0
                        usage["requests"]    += 1
                        if oldest_msg_time is None or ts < oldest_msg_time:
                            oldest_msg_time = ts
                        if newest_msg_time is None or ts > newest_msg_time:
                            newest_msg_time = ts
            except Exception:
                continue

    rl_data = load_rate_limits()
    manual = rl_data.get("providers", {}).get("anthropic", {})
    reset_at = manual.get("reset_at")
    if reset_at:
        try:
            reset_dt = datetime.fromisoformat(reset_at.replace("Z", "+00:00"))
            if reset_dt < datetime.now(timezone.utc):
                reset_at = None
        except Exception:
            reset_at = None

    return {
        "provider": "anthropic",
        "label": "Claude Pro Plan",
        "subscription": "$20/mo",
        "reset_minutes": reset_minutes,
        "window_start": window_start.isoformat(),
        "usage": usage,
        "reset_at": reset_at,
        "oldest_in_window": oldest_msg_time.isoformat() if oldest_msg_time else None,
        "newest_in_window": newest_msg_time.isoformat() if newest_msg_time else None,
        "manual_pct": manual.get("manual_pct"),
        "manual_pct_set_at": manual.get("set_at"),
        "note": "Personal Pro plan — not API billing",
    }


# ---------------------------------------------------------------------------
# Kanban helpers
# ---------------------------------------------------------------------------


def load_kanban() -> list:
    if os.path.exists(KANBAN_PATH):
        with open(KANBAN_PATH) as f:
            return json.load(f)
    return []


def save_kanban(tasks: list) -> None:
    with open(KANBAN_PATH, "w") as f:
        json.dump(tasks, f, indent=2)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})


@app.route("/api/info")
def api_info():
    """Expose dashboard configuration info to the frontend."""
    return jsonify({
        "agentsDir": AGENTS_DIR,
        "workspaceDir": WORKSPACE_DIR,
        "configPath": CONFIG_PATH,
        "gatewayTokenSet": bool(GATEWAY_TOKEN),
        "openclawBin": OPENCLAW_BIN,
        "version": "1.0.0",
        "agentCount": len(discover_agent_ids()),
    })


@app.route("/api/agents")
def api_agents():
    return jsonify(get_agents())


@app.route("/api/usage")
def api_usage():
    return jsonify(parse_usage())


@app.route("/api/rate-limits")
def api_rate_limits():
    return jsonify({"anthropic": compute_anthropic_window()})


@app.route("/api/rate-limits/anthropic", methods=["POST"])
def set_anthropic_pct():
    """
    Manually set the Anthropic rate-limit usage percentage and/or reset time.
    Body: { "percentage": 28, "reset_minutes": 206 }
    """
    data = request.json or {}
    rl = load_rate_limits()
    rl.setdefault("providers", {})
    existing = rl["providers"].get("anthropic", {})

    if "percentage" in data:
        existing["manual_pct"] = float(data["percentage"])
        existing["set_at"] = datetime.now(timezone.utc).isoformat()
    if "reset_minutes" in data:
        existing["reset_at"] = (
            datetime.now(timezone.utc) + timedelta(minutes=float(data["reset_minutes"]))
        ).isoformat()

    rl["providers"]["anthropic"] = existing
    save_rate_limits(rl)
    return jsonify({"ok": True, **existing})


@app.route("/api/model-meta")
def api_model_meta():
    return jsonify(MODEL_META)


# ---------------------------------------------------------------------------
# Kanban API
# ---------------------------------------------------------------------------


@app.route("/api/tasks", methods=["GET"])
def get_tasks():
    tasks = load_kanban()

    agent     = request.args.get("agent")
    priority  = request.args.get("priority")
    due       = request.args.get("due")
    tag       = request.args.get("tag")
    source    = request.args.get("source")
    project   = request.args.get("project")
    requester = request.args.get("requester")
    column    = request.args.get("column")

    if agent:     tasks = [t for t in tasks if t.get("assignee") == agent]
    if priority:  tasks = [t for t in tasks if t.get("priority", "medium") == priority.lower()]
    if tag:       tasks = [t for t in tasks if t.get("tag") == tag]
    if source:    tasks = [t for t in tasks if t.get("source") == source]
    if project:   tasks = [t for t in tasks if t.get("project") == project]
    if requester: tasks = [t for t in tasks if t.get("requester") == requester]
    if column:    tasks = [t for t in tasks if t.get("column") == column]

    if due:
        today = datetime.now(timezone.utc).date()
        filtered = []
        for t in tasks:
            dd = t.get("dueDate")
            if not dd:
                continue
            try:
                d = (
                    datetime.fromisoformat(dd).date() if "T" in dd
                    else datetime.strptime(dd, "%Y-%m-%d").date()
                )
            except Exception:
                continue
            if due == "overdue" and d < today:
                filtered.append(t)
            elif due == "today" and d == today:
                filtered.append(t)
            elif due == "week" and today <= d <= today + timedelta(days=7):
                filtered.append(t)
        tasks = filtered

    return jsonify(tasks)


@app.route("/api/tasks", methods=["POST"])
def create_task():
    data = request.json or {}
    task = {
        "id":           str(uuid.uuid4())[:8],
        "title":        data.get("title", ""),
        "description":  data.get("description", ""),
        "assignee":     data.get("assignee", ""),
        "column":       data.get("column", "backlog"),
        "priority":     data.get("priority", "medium"),
        "dueDate":      data.get("dueDate") or None,
        "createdAt":    datetime.now(timezone.utc).isoformat(),
        "tag":          data.get("tag") or None,
        "source":       data.get("source", "human"),
        "project":      data.get("project") or None,
        "requester":    data.get("requester") or None,
        "blockedReason":data.get("blockedReason") or None,
        "resolution":   data.get("resolution") or None,
        "notes":        data.get("notes") or None,
        "resolvedAt":   data.get("resolvedAt") or None,
    }
    tasks = load_kanban()
    tasks.append(task)
    save_kanban(tasks)
    return jsonify(task), 201


@app.route("/api/tasks/<task_id>", methods=["PUT"])
def update_task(task_id):
    data = request.json or {}
    tasks = load_kanban()
    for t in tasks:
        if t["id"] == task_id:
            t.update({k: v for k, v in data.items() if k != "id"})
            save_kanban(tasks)
            return jsonify(t)
    return jsonify({"error": "not found"}), 404


@app.route("/api/tasks/<task_id>", methods=["DELETE"])
def delete_task(task_id):
    tasks = load_kanban()
    tasks = [t for t in tasks if t["id"] != task_id]
    save_kanban(tasks)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Agent Health
# ---------------------------------------------------------------------------


@app.route("/api/health/detailed")
def health_detailed():
    now = datetime.now(timezone.utc)
    cutoff_5m = now - timedelta(minutes=5)
    cutoff_1h = now - timedelta(hours=1)
    agent_health = {}

    for aid in discover_agent_ids():
        sessions_dir = os.path.join(AGENTS_DIR, aid, "sessions")
        sessions = glob.glob(os.path.join(sessions_dir, "*.jsonl"))

        if not sessions:
            agent_health[aid] = {
                "status": "inactive", "uptime": None, "lastActive": None,
                "lastResponseMs": None, "totalTokens": 0, "errorCount": 0,
                "avgResponseTokens": 0,
            }
            continue

        mtimes = [(s, os.path.getmtime(s)) for s in sessions]
        newest_path, newest_mt = max(mtimes, key=lambda x: x[1])
        oldest_mt = min(mt for _, mt in mtimes)
        newest_ts = datetime.fromtimestamp(newest_mt, tz=timezone.utc)

        if newest_ts >= cutoff_5m:
            status = "online"
        elif newest_ts >= cutoff_1h:
            status = "idle"
        else:
            status = "inactive"

        uptime_seconds = (
            now - datetime.fromtimestamp(oldest_mt, tz=timezone.utc)
        ).total_seconds()

        last_response_ms = None
        total_tokens = 0
        error_count = 0
        output_tokens_list = []

        for sf in sessions:
            try:
                last_user_ts = None
                with open(sf) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if rec.get("type") != "message":
                            continue
                        msg = rec.get("message", {})
                        ts_str = rec.get("timestamp") or msg.get("timestamp")

                        if msg.get("role") == "user" and ts_str:
                            try:
                                last_user_ts = (
                                    datetime.fromtimestamp(ts_str / 1000, tz=timezone.utc)
                                    if isinstance(ts_str, (int, float))
                                    else datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                                )
                            except Exception:
                                pass

                        if msg.get("role") == "assistant":
                            usage = msg.get("usage", {})
                            inp = usage.get("input", 0) or 0
                            out = usage.get("output", 0) or 0
                            total_tokens += inp + out
                            if out:
                                output_tokens_list.append(out)
                            if msg.get("stopReason") == "error":
                                error_count += 1
                            if sf == newest_path and last_user_ts and ts_str:
                                try:
                                    ass_ts = (
                                        datetime.fromtimestamp(ts_str / 1000, tz=timezone.utc)
                                        if isinstance(ts_str, (int, float))
                                        else datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                                    )
                                    last_response_ms = int(
                                        (ass_ts - last_user_ts).total_seconds() * 1000
                                    )
                                except Exception:
                                    pass
            except Exception:
                continue

        agent_health[aid] = {
            "status": status,
            "uptime": int(uptime_seconds),
            "lastActive": newest_ts.isoformat(),
            "lastResponseMs": last_response_ms,
            "totalTokens": total_tokens,
            "errorCount": error_count,
            "avgResponseTokens": (
                int(sum(output_tokens_list) / len(output_tokens_list))
                if output_tokens_list else 0
            ),
        }

    # System metrics
    try:
        st = os.statvfs(WORKSPACE_DIR)
        disk_total = st.f_frsize * st.f_blocks
        disk_free  = st.f_frsize * st.f_bavail
        disk_used  = disk_total - disk_free
    except Exception:
        disk_total = disk_used = disk_free = 0

    session_dir_size = 0
    for agent_dir in glob.glob(os.path.join(AGENTS_DIR, "*")):
        for sf in glob.glob(os.path.join(agent_dir, "sessions", "*.jsonl")):
            try:
                session_dir_size += os.path.getsize(sf)
            except Exception:
                pass

    try:
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    except Exception:
        rss = 0

    return jsonify({
        "agents": agent_health,
        "system": {
            "diskTotal": disk_total,
            "diskUsed": disk_used,
            "diskFree": disk_free,
            "sessionDirSize": session_dir_size,
            "pythonMemoryRss": rss,
        },
    })


# ---------------------------------------------------------------------------
# OpenRouter Credits
# ---------------------------------------------------------------------------

_or_cache: dict = {"data": None, "ts": 0}


@app.route("/api/openrouter/credits")
def api_openrouter_credits():
    now = time.time()
    if _or_cache["data"] and now - _or_cache["ts"] < 60:
        return jsonify(_or_cache["data"])

    key = get_openrouter_key()
    if not key:
        return jsonify({"error": "No OpenRouter API key found. Set OPENCLAW_OPENROUTER_API_KEY or ensure an agent has auth-profiles.json with openrouter:default."}), 404

    try:
        resp = http_requests.get(
            "https://openrouter.ai/api/v1/auth/key",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json().get("data", {})
    except Exception as e:
        return jsonify({"error": str(e)}), 502

    limit           = raw.get("limit") or 0
    limit_remaining = raw.get("limit_remaining") or 0
    usage_weekly    = (limit - limit_remaining) if limit else raw.get("usage", 0)
    usage_monthly   = raw.get("usage", 0)
    is_free_tier    = raw.get("is_free_tier", False)
    pct_used        = (usage_weekly / limit * 100) if limit else 0

    result = {
        "limit":          limit,
        "limit_remaining": limit_remaining,
        "usage_weekly":   round(usage_weekly, 4),
        "usage_monthly":  round(usage_monthly, 4),
        "is_free_tier":   is_free_tier,
        "pct_used":       round(pct_used, 2),
    }
    _or_cache["data"] = result
    _or_cache["ts"]   = now
    return jsonify(result)


# ---------------------------------------------------------------------------
# Request Logs
# ---------------------------------------------------------------------------


@app.route("/api/logs")
def api_logs():
    filter_agent = request.args.get("agent", "")
    filter_model = request.args.get("model", "")
    limit = int(request.args.get("limit", 100))
    entries = []

    for agent_dir in glob.glob(os.path.join(AGENTS_DIR, "*")):
        agent_id = os.path.basename(agent_dir)
        if filter_agent and filter_agent != agent_id:
            continue

        for jsonl_path in glob.glob(os.path.join(agent_dir, "sessions", "*.jsonl")):
            session_name = os.path.basename(jsonl_path)
            try:
                lines = []
                with open(jsonl_path) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            lines.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue

                last_user_text = ""
                for rec in lines:
                    if rec.get("type") != "message":
                        continue
                    msg = rec.get("message", {})

                    if msg.get("role") == "user":
                        content = msg.get("content", "")
                        if isinstance(content, list):
                            last_user_text = " ".join(
                                p.get("text", "")
                                for p in content
                                if isinstance(p, dict) and p.get("type") == "text"
                            )[:100]
                        elif isinstance(content, str):
                            last_user_text = content[:100]
                        continue

                    if msg.get("role") != "assistant":
                        continue

                    model = msg.get("model", "unknown")
                    if filter_model and filter_model.lower() not in model.lower():
                        continue

                    usage = msg.get("usage", {})
                    cost_obj = usage.get("cost", {})
                    cost = (cost_obj.get("total", 0) if isinstance(cost_obj, dict) else 0) or 0

                    ts_str = rec.get("timestamp") or msg.get("timestamp")
                    ts_iso = None
                    if ts_str:
                        try:
                            if isinstance(ts_str, (int, float)):
                                ts_iso = datetime.fromtimestamp(ts_str / 1000, tz=timezone.utc).isoformat()
                            else:
                                ts_iso = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).isoformat()
                        except Exception:
                            pass

                    entries.append({
                        "timestamp":     ts_iso,
                        "agent":         agent_id,
                        "session":       session_name,
                        "model":         model,
                        "provider":      msg.get("provider", ""),
                        "input_tokens":  usage.get("input", 0) or 0,
                        "output_tokens": usage.get("output", 0) or 0,
                        "cache_read":    usage.get("cacheRead", 0) or 0,
                        "cache_write":   usage.get("cacheWrite", 0) or 0,
                        "cost":          cost,
                        "stopReason":    msg.get("stopReason", ""),
                        "errorMessage":  msg.get("error", ""),
                        "prompt_preview": last_user_text,
                    })
            except Exception:
                continue

    entries.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
    return jsonify(entries[:limit])


# ---------------------------------------------------------------------------
# Agent Notification
# ---------------------------------------------------------------------------


@app.route("/api/notify-agent", methods=["POST"])
def notify_agent():
    """
    Send a system event to wake/notify the agent via the openclaw CLI.
    Requires OPENCLAW_GATEWAY_TOKEN to be set.
    """
    if not GATEWAY_TOKEN:
        return jsonify({
            "ok": False,
            "error": "OPENCLAW_GATEWAY_TOKEN is not configured. Set it in your .env file.",
        }), 400

    if not OPENCLAW_BIN or not os.path.isfile(OPENCLAW_BIN):
        return jsonify({
            "ok": False,
            "error": f"openclaw binary not found at '{OPENCLAW_BIN}'. Set OPENCLAW_BIN in your .env file.",
        }), 400

    import subprocess
    data = request.json or {}
    message = data.get(
        "message",
        "New task in your Agent Inbox on the Kanban board. Check the dashboard and pick it up.",
    )
    try:
        result = subprocess.run(
            [OPENCLAW_BIN, "system", "event", "--text", message, "--mode", "now", "--token", GATEWAY_TOKEN],
            capture_output=True, text=True, timeout=10,
        )
        ok = result.returncode == 0
        return jsonify({
            "ok": ok,
            "output": result.stdout.strip(),
            "error": result.stderr.strip() if not ok else None,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=False)
