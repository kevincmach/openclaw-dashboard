# Contributing to OpenClaw Dashboard

First off — thanks for taking the time to contribute! Whether it's a bug fix, a new feature, or just improving the docs, every contribution helps.

This document explains how to get set up, what the workflow looks like, and what makes a great pull request.

---

## 📋 Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [How to Contribute](#how-to-contribute)
- [Branch Naming](#branch-naming)
- [Commit Messages](#commit-messages)
- [Opening a Pull Request](#opening-a-pull-request)
- [Reporting Bugs](#reporting-bugs)
- [Requesting Features](#requesting-features)
- [Good First Issues](#good-first-issues)

---

## Code of Conduct

This project follows a simple rule: **be kind and constructive.** See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for details.

---

## Getting Started

### Prerequisites

- Python 3.10+
- [OpenClaw](https://openclaw.ai) installed with at least one configured agent
- Git

### Fork & Clone

```bash
# 1. Fork the repo on GitHub (top-right "Fork" button)

# 2. Clone your fork
git clone https://github.com/YOUR_USERNAME/openclaw-dashboard.git
cd openclaw-dashboard

# 3. Add the upstream remote so you can pull future changes
git remote add upstream https://github.com/profmatcha/openclaw-dashboard.git
```

---

## Development Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Copy the example env file and fill in your values
cp .env.example .env
# At minimum, set OPENCLAW_GATEWAY_TOKEN in .env

# Run the dashboard
python3 app.py
```

Open [http://localhost:5050](http://localhost:5050) — you should see your agents.

### Keeping your fork up to date

```bash
git fetch upstream
git checkout main
git merge upstream/main
```

---

## How to Contribute

### Workflow overview

```
fork → branch → code → test → PR → review → merge
```

1. **Check existing issues** — someone may already be working on it
2. **Open an issue first** for large changes — alignment before effort
3. **Create a branch** from `main`
4. **Make your changes** with clear, focused commits
5. **Test locally** — make sure the dashboard still starts and the relevant features work
6. **Open a PR** against `main`

---

## Branch Naming

Use one of these prefixes depending on the type of change:

| Prefix | When to use |
|---|---|
| `feature/` | New functionality |
| `fix/` | Bug fixes |
| `docs/` | Documentation only |
| `refactor/` | Code cleanup with no behavior change |
| `chore/` | Dependency updates, tooling, CI |

**Examples:**
```
feature/dark-mode-toggle
fix/timeline-utc-offset
docs/improve-api-reference
refactor/extract-session-parser
```

---

## Commit Messages

Follow the [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>: <short description>

[optional body explaining the why, not the what]
```

**Types:** `feat`, `fix`, `docs`, `refactor`, `chore`, `test`

**Examples:**
```
feat: add CSV export for usage data
fix: correct UTC offset in 24-hour timeline chart
docs: add screenshot to README
refactor: extract JSONL parser into helper module
```

Keep the subject line under 72 characters. Use the body for context when the change isn't obvious.

---

## Opening a Pull Request

1. Push your branch to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```

2. Open a PR on GitHub against `main` in the upstream repo

3. Fill out the PR template (it will auto-populate)

4. A maintainer will review and leave feedback — please respond to all comments

### What makes a great PR

- **Focused** — one thing per PR. Avoid combining unrelated changes
- **Tested** — confirmed working locally, ideally with a screenshot for UI changes
- **Documented** — update README or inline docs if behavior changes
- **Small** — smaller PRs get reviewed and merged faster

---

## Reporting Bugs

Use the **Bug Report** issue template. Include:

- What you expected to happen
- What actually happened
- Steps to reproduce
- Your Python version and OS
- Relevant logs from `journalctl -u openclaw-dashboard` or console output

---

## Requesting Features

Use the **Feature Request** issue template. Think about:

- What problem does this solve?
- Who benefits from it?
- Is there a simpler alternative?

You don't need a full spec — a clear problem statement is enough to start a conversation.

---

## Good First Issues

New to open source? Look for issues tagged [`good first issue`](../../issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22).

These are intentionally scoped to be approachable without deep knowledge of the codebase. If you get stuck, comment on the issue — we're happy to help.

---

## Questions?

Open a [GitHub Discussion](../../discussions) or drop a message in the [OpenClaw Discord](https://discord.com/invite/clawd).
