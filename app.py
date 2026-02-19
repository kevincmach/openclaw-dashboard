#!/usr/bin/env python3
"""OpenClaw Agent Management Dashboard"""

import json
import os
import glob
import uuid
import resource
import time
import requests as http_requests
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, request, render_template

app = Flask(__name__)

CONFIG_PATH = "/home/kevin/.openclaw/openclaw.json"
AGENTS_DIR = "/home/kevin/.openclaw/agents"
WORKSPACE_DIR = "/home/kevin/.openclaw/workspace"
KANBAN_PATH = os.path.join(os.path.dirname(__file__), "kanban.json")

AGENT_COLORS = {
    "main": "#6366f1",
    "projects": "#10b981",
    "games": "#f59e0b",
    "clawrence-studios": "#ef4444",
}

RATE_LIMIT_FILE = os.path.join(os.path.dirname(__file__), "rate_limits.json")

MODEL_META = {
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


def load_rate_limits():
    if os.path.exists(RATE_LIMIT_FILE):
        with open(RATE_LIMIT_FILE) as f:
            return json.load(f)
    return {"providers": {}}


def save_rate_limits(data):
    with open(RATE_LIMIT_FILE, "w") as f:
        json.dump(data, f, indent=2)


def compute_anthropic_window():
    """Compute Anthropic Pro usage in the current rolling window."""
    reset_minutes = MODEL_META["anthropic/claude-opus-4-6"]["reset_minutes"]
    window_start = datetime.now(timezone.utc) - timedelta(minutes=reset_minutes)
    window_start_iso = window_start.isoformat()

    usage = {"input": 0, "output": 0, "requests": 0, "cache_read": 0, "cache_write": 0}
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
                        if msg.get("role") != "assistant":
                            continue
                        provider = msg.get("provider", "")
                        if provider != "anthropic":
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
                        usage["input"] += (u.get("input", 0) or 0)
                        usage["output"] += (u.get("output", 0) or 0)
                        usage["cache_read"] += (u.get("cacheRead", 0) or 0)
                        usage["cache_write"] += (u.get("cacheWrite", 0) or 0)
                        usage["requests"] += 1

                        if oldest_msg_time is None or ts < oldest_msg_time:
                            oldest_msg_time = ts
                        if newest_msg_time is None or ts > newest_msg_time:
                            newest_msg_time = ts
            except Exception:
                continue

    rl_data = load_rate_limits()
    manual = rl_data.get("providers", {}).get("anthropic", {})

    # Use manually calibrated reset time if set
    reset_at = manual.get("reset_at")
    if reset_at:
        try:
            reset_dt = datetime.fromisoformat(reset_at.replace("Z", "+00:00"))
            # If reset time has passed, clear it
            if reset_dt < datetime.now(timezone.utc):
                reset_at = None
        except Exception:
            reset_at = None

    return {
        "provider": "anthropic",
        "label": "Claude Pro Plan",
        "subscription": "$20/mo",
        "reset_minutes": reset_minutes,
        "window_start": window_start_iso,
        "usage": usage,
        "reset_at": reset_at,
        "oldest_in_window": oldest_msg_time.isoformat() if oldest_msg_time else None,
        "newest_in_window": newest_msg_time.isoformat() if newest_msg_time else None,
        "manual_pct": manual.get("manual_pct"),
        "manual_pct_set_at": manual.get("set_at"),
        "note": MODEL_META["anthropic/claude-opus-4-6"]["note"],
    }


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def discover_agent_ids():
    """Auto-discover agents by scanning the agents directory."""
    agents = []
    for entry in os.scandir(AGENTS_DIR):
        if entry.is_dir():
            agents.append(entry.name)
    return sorted(agents)


def get_default_model():
    """Read the default model from config."""
    try:
        cfg = load_config()
        m = cfg.get("agents", {}).get("defaults", {}).get("model", {})
        if isinstance(m, dict):
            return m.get("primary", "unknown")
        return m or "unknown"
    except Exception:
        return "unknown"


def get_agent_channel_info(aid):
    """Try to infer channel info from config bindings (may not exist)."""
    try:
        cfg = load_config()
        bindings = cfg.get("bindings", [])
        for b in bindings:
            if b.get("agentId") == aid:
                match = b.get("match", {})
                return match.get("channel", "—"), match.get("accountId", "—")
    except Exception:
        pass
    # Fallback: peek at sessions.json if it exists
    sessions_json = os.path.join(AGENTS_DIR, aid, "sessions", "sessions.json")
    if os.path.exists(sessions_json):
        try:
            with open(sessions_json) as f:
                data = json.load(f)
            if isinstance(data, list) and data:
                last = data[-1]
                key = last.get("key", "")
                # key format: agent:main:discord:channel:12345
                parts = key.split(":")
                if len(parts) >= 3:
                    return parts[2], "—"
        except Exception:
            pass
    return "—", "—"


def get_agents():
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
            newest_mt = max(session_mtimes)
            last_active = datetime.fromtimestamp(newest_mt, tz=timezone.utc).isoformat()

        # Last 3 session timestamps
        session_mtimes.sort(reverse=True)
        last_3 = [datetime.fromtimestamp(t, tz=timezone.utc).isoformat() for t in session_mtimes[:3]]

        result.append({
            "id": aid,
            "model": default_model,
            "channel": channel,
            "accountId": account_id,
            "color": AGENT_COLORS.get(aid, "#8b5cf6"),
            "sessionCount": len(sessions),
            "activeSessionCount": active_count,
            "totalSessionCount": len(sessions),
            "lastSessionTimestamps": last_3,
            "lastActive": last_active,
        })
    return result


def parse_usage():
    """Parse all session JSONL files for usage data."""
    totals = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "cost": 0.0, "openrouterCost": 0.0, "proPlanCost": 0.0}
    by_model = {}
    timeline = []
    by_agent = {}
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
                        inp = usage.get("input", 0) or 0
                        out = usage.get("output", 0) or 0
                        cr = usage.get("cacheRead", 0) or 0
                        cw = usage.get("cacheWrite", 0) or 0
                        cost_obj = usage.get("cost", {})
                        cost = cost_obj.get("total", 0) if isinstance(cost_obj, dict) else 0
                        cost = cost or 0

                        provider = msg.get("provider", "unknown")
                        totals["input"] += inp
                        totals["output"] += out
                        totals["cacheRead"] += cr
                        totals["cacheWrite"] += cw
                        totals["cost"] += cost
                        if provider == "anthropic":
                            totals["proPlanCost"] += cost
                        elif provider == "m2-macmini-ollama-local":
                            totals.setdefault("ollamaCost", 0.0)
                            totals["ollamaCost"] += cost
                        else:
                            totals["openrouterCost"] += cost
                        agent_totals["input"] += inp
                        agent_totals["output"] += out
                        agent_totals["cost"] += cost

                        model = msg.get("model", "unknown")
                        # Key by provider:model for clear labeling
                        model_key = f"{provider}/{model}" if provider not in ("unknown", "openclaw") else model
                        if model_key not in by_model:
                            by_model[model_key] = {"input": 0, "output": 0, "cost": 0.0, "calls": 0, "provider": provider}
                        by_model[model_key]["input"] += inp
                        by_model[model_key]["output"] += out
                        by_model[model_key]["cost"] += cost
                        by_model[model_key]["calls"] += 1

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
                                        "input": inp,
                                        "output": out,
                                        "cost": cost,
                                        "agent": agent_id,
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


def load_kanban():
    if os.path.exists(KANBAN_PATH):
        with open(KANBAN_PATH) as f:
            return json.load(f)
    return []


def save_kanban(tasks):
    with open(KANBAN_PATH, "w") as f:
        json.dump(tasks, f, indent=2)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()})


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
    """Set usage % and/or reset time. Accepts:
    - percentage: current usage % (0-100)
    - reset_minutes: minutes until next reset (calculates reset_at from now)
    """
    data = request.json or {}
    rl = load_rate_limits()
    if "providers" not in rl:
        rl["providers"] = {}
    existing = rl.get("providers", {}).get("anthropic", {})

    pct = data.get("percentage")
    reset_min = data.get("reset_minutes")

    if pct is not None:
        existing["manual_pct"] = float(pct)
        existing["set_at"] = datetime.now(timezone.utc).isoformat()

    if reset_min is not None:
        reset_at = datetime.now(timezone.utc) + timedelta(minutes=float(reset_min))
        existing["reset_at"] = reset_at.isoformat()

    rl["providers"]["anthropic"] = existing
    save_rate_limits(rl)
    return jsonify({"ok": True, **existing})


@app.route("/api/model-meta")
def api_model_meta():
    return jsonify(MODEL_META)


@app.route("/api/tasks", methods=["GET"])
def get_tasks():
    tasks = load_kanban()
    # Filtering
    agent = request.args.get("agent")
    priority = request.args.get("priority")
    due = request.args.get("due")  # overdue, today, week
    tag = request.args.get("tag")
    source = request.args.get("source")
    project = request.args.get("project")
    requester = request.args.get("requester")

    if agent:
        tasks = [t for t in tasks if t.get("assignee") == agent]
    if priority:
        tasks = [t for t in tasks if t.get("priority", "medium") == priority.lower()]
    if tag:
        tasks = [t for t in tasks if t.get("tag") == tag]
    if source:
        tasks = [t for t in tasks if t.get("source") == source]
    if project:
        tasks = [t for t in tasks if t.get("project") == project]
    if requester:
        tasks = [t for t in tasks if t.get("requester") == requester]
    if due:
        now = datetime.now(timezone.utc).date()
        filtered = []
        for t in tasks:
            dd = t.get("dueDate")
            if not dd:
                if due == "all":
                    filtered.append(t)
                continue
            try:
                d = datetime.fromisoformat(dd).date() if "T" in dd else datetime.strptime(dd, "%Y-%m-%d").date()
            except Exception:
                continue
            if due == "overdue" and d < now:
                filtered.append(t)
            elif due == "today" and d == now:
                filtered.append(t)
            elif due == "week" and now <= d <= now + timedelta(days=7):
                filtered.append(t)
            elif due == "all":
                filtered.append(t)
        if due != "all":
            tasks = filtered

    return jsonify(tasks)


@app.route("/api/tasks", methods=["POST"])
def create_task():
    data = request.json
    task = {
        "id": str(uuid.uuid4())[:8],
        "title": data.get("title", ""),
        "description": data.get("description", ""),
        "assignee": data.get("assignee", ""),
        "column": data.get("column", "backlog"),
        "priority": data.get("priority", "medium"),
        "dueDate": data.get("dueDate") or None,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "tag": data.get("tag") or None,
        "source": data.get("source", "human"),
        "project": data.get("project") or None,
        "requester": data.get("requester") or None,
        "blockedReason": data.get("blockedReason") or None,
        "resolution": data.get("resolution") or None,
        "notes": data.get("notes") or None,
        "resolvedAt": data.get("resolvedAt") or None,
    }
    tasks = load_kanban()
    tasks.append(task)
    save_kanban(tasks)
    return jsonify(task), 201


@app.route("/api/tasks/<task_id>", methods=["PUT"])
def update_task(task_id):
    data = request.json
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


@app.route("/api/health/detailed")
def health_detailed():
    now = datetime.now(timezone.utc)
    cutoff_5m = now - timedelta(minutes=5)
    cutoff_1h = now - timedelta(hours=1)

    agent_health = {}
    agent_ids = discover_agent_ids()

    for aid in agent_ids:
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
        mtimes.sort(key=lambda x: x[1])
        newest_path, newest_mt = max(mtimes, key=lambda x: x[1])
        oldest_mt = mtimes[0][1]
        newest_ts = datetime.fromtimestamp(newest_mt, tz=timezone.utc)

        if newest_ts >= cutoff_5m:
            status = "online"
        elif newest_ts >= cutoff_1h:
            status = "idle"
        else:
            status = "inactive"

        uptime_seconds = (now - datetime.fromtimestamp(oldest_mt, tz=timezone.utc)).total_seconds()

        # Parse newest session for response latency
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

                        if msg.get("role") == "user":
                            if ts_str:
                                try:
                                    if isinstance(ts_str, (int, float)):
                                        last_user_ts = datetime.fromtimestamp(ts_str / 1000, tz=timezone.utc)
                                    else:
                                        last_user_ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
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

                            # Latency from newest session only
                            if sf == newest_path and last_user_ts and ts_str:
                                try:
                                    if isinstance(ts_str, (int, float)):
                                        ass_ts = datetime.fromtimestamp(ts_str / 1000, tz=timezone.utc)
                                    else:
                                        ass_ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                                    last_response_ms = int((ass_ts - last_user_ts).total_seconds() * 1000)
                                except Exception:
                                    pass
            except Exception:
                continue

        avg_out = int(sum(output_tokens_list) / len(output_tokens_list)) if output_tokens_list else 0

        agent_health[aid] = {
            "status": status,
            "uptime": int(uptime_seconds),
            "lastActive": newest_ts.isoformat(),
            "lastResponseMs": last_response_ms,
            "totalTokens": total_tokens,
            "errorCount": error_count,
            "avgResponseTokens": avg_out,
        }

    # System health
    try:
        st = os.statvfs(WORKSPACE_DIR)
        disk_total = st.f_frsize * st.f_blocks
        disk_free = st.f_frsize * st.f_bavail
        disk_used = disk_total - disk_free
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
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024  # bytes on Linux
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
        }
    })


# --- OpenRouter Credits Cache ---
_or_cache = {"data": None, "ts": 0}

AUTH_PROFILES_PATH = "/home/kevin/.openclaw/agents/clawrence/agent/auth-profiles.json"


def get_openrouter_key():
    with open(AUTH_PROFILES_PATH) as f:
        profiles = json.load(f).get("profiles", {})
    p = profiles.get("openrouter:default", {})
    return p.get("apiKey") or p.get("key")


@app.route("/api/openrouter/credits")
def api_openrouter_credits():
    now = time.time()
    if _or_cache["data"] and now - _or_cache["ts"] < 60:
        return jsonify(_or_cache["data"])

    key = get_openrouter_key()
    if not key:
        return jsonify({"error": "No OpenRouter API key found"}), 500

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

    limit = raw.get("limit") or 0
    limit_remaining = raw.get("limit_remaining") or 0
    usage_weekly = (limit - limit_remaining) if limit else raw.get("usage", 0)
    usage_monthly = raw.get("usage", 0)
    is_free_tier = raw.get("is_free_tier", False)
    pct_used = (usage_weekly / limit * 100) if limit else 0

    result = {
        "limit": limit,
        "limit_remaining": limit_remaining,
        "usage_weekly": round(usage_weekly, 4),
        "usage_monthly": round(usage_monthly, 4),
        "is_free_tier": is_free_tier,
        "pct_used": round(pct_used, 2),
        "raw": raw,
    }
    _or_cache["data"] = result
    _or_cache["ts"] = now
    return jsonify(result)


# --- Request Logs ---
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
                            parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
                            last_user_text = " ".join(parts)[:100]
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
                    cost = cost_obj.get("total", 0) if isinstance(cost_obj, dict) else 0

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
                        "timestamp": ts_iso,
                        "agent": agent_id,
                        "session": session_name,
                        "model": model,
                        "provider": msg.get("provider", ""),
                        "input_tokens": usage.get("input", 0) or 0,
                        "output_tokens": usage.get("output", 0) or 0,
                        "cache_read": usage.get("cacheRead", 0) or 0,
                        "cache_write": usage.get("cacheWrite", 0) or 0,
                        "cost": cost or 0,
                        "stopReason": msg.get("stopReason", ""),
                        "errorMessage": msg.get("error", ""),
                        "prompt_preview": last_user_text,
                    })
            except Exception:
                continue

    entries.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
    return jsonify(entries[:limit])


GATEWAY_TOKEN = "e94ae76075af3f67ab7446c7b5cf12d9e89368dd159fca7d"


@app.route("/api/notify-agent", methods=["POST"])
def notify_agent():
    """Wake the agent via openclaw system event CLI."""
    import subprocess
    data = request.json or {}
    message = data.get("message", "New task in your Agent Inbox on the Kanban board. Check http://localhost:5050 and pick it up.")
    try:
        result = subprocess.run(
            ["/home/kevin/.npm-global/bin/openclaw", "system", "event", "--text", message, "--mode", "now", "--token", GATEWAY_TOKEN],
            capture_output=True, text=True, timeout=10
        )
        ok = result.returncode == 0
        return jsonify({"ok": ok, "output": result.stdout.strip(), "error": result.stderr.strip() if not ok else None})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)
