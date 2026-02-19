# OpenClaw Dashboard

Agent management dashboard for OpenClaw — view agents, monitor usage, manage tasks.

## Setup

```bash
pip install flask
cd /home/kevin/.openclaw/workspace/projects/openclaw-dashboard
python3 app.py
```

Dashboard runs at **http://localhost:5050**

## Systemd Service

```bash
sudo cp openclaw-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now openclaw-dashboard
```

## Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Dashboard UI |
| `/api/health` | GET | Health check |
| `/api/agents` | GET | Agent list with config |
| `/api/usage` | GET | Token usage & costs |
| `/api/tasks` | GET/POST | List/create tasks |
| `/api/tasks/<id>` | PUT/DELETE | Update/delete task |

## Features

- **Agents** — View all configured agents, models, channel bindings, session counts
- **Usage** — Token totals, per-model breakdown, 24h timeline chart, per-agent costs
- **Kanban** — Drag-and-drop task board with backlog/in-progress/done columns
