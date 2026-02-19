# 🐾 OpenClaw Dashboard

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![OpenClaw](https://img.shields.io/badge/built%20for-OpenClaw-8b5cf6)](https://openclaw.ai)

A self-hosted web dashboard for monitoring and managing your [OpenClaw](https://github.com/openclaw/openclaw) AI agents. Track token usage, visualize activity, manage tasks via Kanban, and keep an eye on agent health — all from one place.

<!-- Add screenshots here -->

---

## 🧠 Why I Built This

I run several OpenClaw AI agents across different projects and had no good way to see what they were all doing. I wanted to know which agent was active, how many tokens it burned today, whether it was hitting rate limits, and what tasks were in its queue — all without digging through log files or jumping between terminals.

So I built this: a single dashboard that reads directly from OpenClaw's on-disk session data, no extra infrastructure required. It started as a personal tool and evolved into something I thought the broader OpenClaw community might find useful.

If you're running more than one agent and want visibility into what's happening, this is for you.

---

## ✨ Features

- **Agent Monitor** — See all your agents at a glance: status (active/idle), last activity, session counts, channel bindings
- **Usage Analytics** — Token counts (input/output/cache), cost breakdown by model and agent, 24-hour activity timeline
- **Rate Limit Monitor** — Track your Claude Pro rolling window usage with a visual bar and manual calibration
- **OpenRouter Credits** — Live credit balance and weekly spend if you use OpenRouter models
- **Agent Health** — Per-agent status dots (online/idle/inactive), uptime, response latency, error counts
- **Request Logs** — Filterable table of every LLM request across all agents and sessions
- **Kanban Board** — Task management with agent inbox support, drag-and-drop, priority sorting, and full edit modals
- **Zero config for standard installs** — Works out of the box against a standard `~/.openclaw` directory

---

## 📋 Requirements

- Python 3.10+
- [OpenClaw](https://openclaw.ai) installed and configured (`~/.openclaw/` directory present)
- At least one agent configured and producing session data

---

## 🚀 Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/your-org/openclaw-dashboard.git
cd openclaw-dashboard
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

> **Tip:** Use a virtual environment to keep things clean:
> ```bash
> python3 -m venv .venv && source .venv/bin/activate
> pip install -r requirements.txt
> ```

### 3. Configure

```bash
cp .env.example .env
```

Open `.env` and set at minimum:

```bash
# Your gateway token (for the "Notify Agent" button on the Kanban board)
# Find it in ~/.openclaw/openclaw.json or: openclaw gateway status
OPENCLAW_GATEWAY_TOKEN=your_token_here
```

Everything else defaults to `~/.openclaw` — no changes needed for a standard install.

### 4. Run

```bash
python3 app.py
```

Open [http://localhost:5050](http://localhost:5050) in your browser.

---

## ⚙️ Configuration

All configuration is via environment variables. You can set them in `.env` (recommended) or export them in your shell.

| Variable | Default | Description |
|---|---|---|
| `OPENCLAW_BASE_DIR` | `~/.openclaw` | Root of your OpenClaw data directory |
| `OPENCLAW_AGENTS_DIR` | `{BASE_DIR}/agents` | Directory containing agent subdirectories |
| `OPENCLAW_WORKSPACE_DIR` | `{BASE_DIR}/workspace` | Workspace root (used for disk stats) |
| `OPENCLAW_CONFIG_PATH` | `{BASE_DIR}/openclaw.json` | Main OpenClaw config file |
| `OPENCLAW_GATEWAY_TOKEN` | _(empty)_ | Gateway auth token for agent notifications |
| `OPENCLAW_OPENROUTER_API_KEY` | _(auto)_ | OpenRouter API key override (auto-discovered if blank) |
| `OPENCLAW_BIN` | _(auto)_ | Path to the `openclaw` binary (auto-detected via PATH) |
| `DASHBOARD_PORT` | `5050` | Port to listen on |
| `DASHBOARD_HOST` | `0.0.0.0` | Bind address |
| `DASHBOARD_SECRET_KEY` | `openclaw-dashboard` | Flask session secret (change in production) |

### Finding your Gateway Token

```bash
# Option 1: Check openclaw.json
cat ~/.openclaw/openclaw.json | grep -i token

# Option 2: Via CLI
openclaw gateway status
```

---

## 🗂️ OpenClaw Directory Layout

The dashboard reads directly from OpenClaw's on-disk data. Here's what it expects:

```
~/.openclaw/
├── openclaw.json          # Main config (agents, bindings, model defaults)
├── agents/
│   ├── myagent/           # One directory per agent (auto-discovered)
│   │   ├── agent/
│   │   │   └── auth-profiles.json   # API keys (OpenRouter key discovered here)
│   │   └── sessions/
│   │       ├── session-abc123.jsonl  # Session transcripts (JSONL format)
│   │       └── sessions.json         # Session index
│   └── anotheragent/
│       └── sessions/
│           └── ...
└── workspace/             # Agent workspace files
```

**Agents are auto-discovered** — any subdirectory inside `agents/` is treated as an agent. No configuration needed.

**Colors are auto-assigned** — each agent gets a stable color derived from its name. No hardcoding required.

---

## 🗒️ Kanban Workflow

The Kanban board supports a multi-agent workflow:

### Columns

| Column | Purpose |
|---|---|
| **📥 Agent Inbox** | Tasks waiting to be picked up by an agent |
| **📋 Backlog** | Planned work, not yet started |
| **🔄 In Progress** | Active work |
| **🚧 Blocked** | Blocked — set a blocked reason |
| **✅ Done** | Completed — resolution + notes logged |

### Human → Agent workflow

1. Create a task in **Agent Inbox** and assign it to your agent
2. Click **🔔 Notify Agent** — sends a system event to wake the agent
3. The agent picks up the task, moves it to **In Progress**, does the work
4. Agent closes the ticket with Resolution + Notes, moves to **Done**

### Agent API usage (for agent developers)

Agents can manage tasks via the REST API:

```bash
# Check agent inbox
curl "http://localhost:5050/api/tasks?column=agent-inbox&agent=myagent"

# Move task to in-progress
curl -X PUT "http://localhost:5050/api/tasks/{id}" \
  -H "Content-Type: application/json" \
  -d '{"column": "in-progress"}'

# Close with resolution
curl -X PUT "http://localhost:5050/api/tasks/{id}" \
  -H "Content-Type: application/json" \
  -d '{
    "column": "done",
    "resolution": "- Fixed the bug\n- Restarted the service",
    "notes": "Root cause: stale config path after agent rename",
    "resolvedAt": "2026-02-19T18:00:00Z"
  }'
```

### Task card detail modal

Click any Kanban card to open a full edit modal:
- Edit all fields inline
- Change status (column) without drag-and-drop
- Resolution & Notes section prominently displayed
- `resolvedAt` auto-stamped when first moved to **Done**
- Cards display a `✅ Resolution logged` indicator when notes exist

---

## 📊 API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Dashboard UI |
| `GET` | `/api/health` | Health check |
| `GET` | `/api/info` | Dashboard config info |
| `GET` | `/api/agents` | List all agents with metadata |
| `GET` | `/api/usage` | Aggregated token usage and timeline |
| `GET` | `/api/rate-limits` | Anthropic Pro rate limit window status |
| `POST` | `/api/rate-limits/anthropic` | Update manual usage % and reset time |
| `GET` | `/api/health/detailed` | Per-agent health + system metrics |
| `GET` | `/api/openrouter/credits` | OpenRouter credit balance (cached 60s) |
| `GET` | `/api/logs` | Request log entries (filterable) |
| `GET` | `/api/tasks` | List Kanban tasks (filterable) |
| `POST` | `/api/tasks` | Create a new task |
| `PUT` | `/api/tasks/{id}` | Update a task |
| `DELETE` | `/api/tasks/{id}` | Delete a task |
| `POST` | `/api/notify-agent` | Send system event to wake agents |

### Log query parameters

`GET /api/logs?agent=myagent&model=claude&limit=100`

### Task query parameters

`GET /api/tasks?column=agent-inbox&agent=myagent&priority=urgent&tag=infra&source=human`

---

## 🔧 Running as a systemd Service

For persistent background operation:

### 1. Edit the service file

Open `openclaw-dashboard.service` and update `User`, `WorkingDirectory`, and `EnvironmentFile` to match your paths.

### 2. Install and enable

```bash
sudo cp openclaw-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now openclaw-dashboard
```

### 3. Check status

```bash
systemctl status openclaw-dashboard
journalctl -u openclaw-dashboard -f
```

---

## 🔍 Troubleshooting

### Dashboard shows no agents

The `OPENCLAW_AGENTS_DIR` doesn't contain any subdirectories, or it's pointing to the wrong path. Check:

```bash
ls ~/.openclaw/agents/
# Should show one directory per agent
```

If your OpenClaw is installed elsewhere, set `OPENCLAW_BASE_DIR` in your `.env`.

### `/api/openrouter/credits` returns 404 / "No key found"

The dashboard looks for an OpenRouter key by scanning `agents/*/agent/auth-profiles.json`. If you don't use OpenRouter, this is expected and harmless — the widget in the UI will show gracefully.

To fix: set `OPENCLAW_OPENROUTER_API_KEY=sk-or-...` in your `.env`.

### "Notify Agent" button fails

Two things required:
1. `OPENCLAW_GATEWAY_TOKEN` must be set in `.env`
2. The `openclaw` binary must be in your PATH (or set `OPENCLAW_BIN`)

```bash
which openclaw         # should print a path
openclaw gateway status  # should show the gateway token
```

### Rate limit bar shows 0% / no data

The rate limit bar is based on session data in `~/.openclaw/agents/*/sessions/*.jsonl`. If your agents haven't generated sessions yet, it will show empty. The manual calibration button lets you set the percentage directly from the Anthropic dashboard.

### Usage shows no timeline data

Timeline data only covers the last 24 hours (based on session file timestamps). Older sessions are still counted in totals but not plotted.

### Port 5050 already in use

```bash
DASHBOARD_PORT=8080 python3 app.py
# or set it in .env
```

---

## 🏗️ Architecture Notes

- **Pure JSONL parsing** — no database required. All data is read directly from OpenClaw's session files
- **Stateless UI** — the frontend polls the API every 30-60 seconds; no WebSocket needed
- **Kanban storage** — tasks are stored in `kanban.json` (flat file, next to `app.py`)
- **Rate limit state** — stored in `rate_limits.json` (manual calibration data only)

---

## 🤝 Contributing

Pull requests are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow — it covers forking, branch naming, commit conventions, and what makes a great PR.

**Ideas for first contributions** (tagged [`good first issue`](../../issues?q=is%3Aissue+label%3A%22good+first+issue%22) on GitHub):

- 🌓 Dark/light theme toggle
- 📤 Export usage data to CSV
- 📊 Agent comparison charts
- 🔔 Webhook support for task notifications
- 🖥️ Multi-instance support (monitor a fleet of OpenClaw nodes)
- 🌍 Timezone-aware timestamps throughout the UI

Not sure where to start? Open a [GitHub Discussion](../../discussions) or ask in the [OpenClaw Discord](https://discord.com/invite/clawd).

---

## 📄 License

MIT — do whatever you want with it. Attribution appreciated but not required. See [LICENSE](LICENSE).

## 📝 Changelog

See [CHANGELOG.md](CHANGELOG.md) for a full history of releases and what changed in each.

---

*Built with ❤️ for the [OpenClaw](https://openclaw.ai) community.*
