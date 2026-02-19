# Changelog

All notable changes to OpenClaw Dashboard will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] — 2026-02-19

### 🎉 Initial Release

#### Added
- **Agent Monitor** — live status cards for all auto-discovered OpenClaw agents
- **Usage Analytics** — token counts (input/output/cache), cost by model and agent, 24-hour activity timeline
- **Rate Limit Monitor** — Claude Pro rolling window tracker with manual calibration
- **OpenRouter Credits** — live credit balance and weekly spend widget
- **Agent Health Panel** — per-agent status (online/idle/inactive), uptime, response latency, error counts, token averages
- **Request Logs** — filterable table of every LLM request across all agents and sessions
- **Kanban Board** — full task management with drag-and-drop, 5 columns (Agent Inbox, Backlog, In Progress, Blocked, Done), priority sorting, tag/project/requester filters
- **Task Detail Modal** — click any Kanban card to open a full edit view with inline status changes, resolution & notes fields, auto-stamped `resolvedAt`
- **Notify Agent** — button to send a system event to agents via the OpenClaw gateway
- **Environment variable configuration** — all paths and tokens configurable via `.env`; zero-config for standard `~/.openclaw` installs
- **Dynamic agent discovery** — any subdirectory in `agents/` is automatically detected
- **Dynamic agent colors** — stable color assignment from agent name; no hardcoding needed
- **Dynamic OpenRouter key discovery** — scans all agent `auth-profiles.json` files automatically
- **`/api/info` endpoint** — runtime config introspection
- **`requirements.txt`**, **`.env.example`**, **`.gitignore`**, **systemd service unit**
- Full **README** with quickstart, configuration reference, API docs, Kanban workflow guide, systemd setup, and troubleshooting

---

## [Unreleased]

> Changes that are merged but not yet in a tagged release will appear here.

<!-- Example format:
### Added
- Feature X

### Fixed
- Bug Y

### Changed
- Behavior Z
-->
