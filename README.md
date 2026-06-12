# Orbit 🛸

> A Slack bot that lets you interact with GitHub in natural language, powered by Claude and MCP.

Ask Orbit things like:
- *"Summarize the open PRs on my-org/my-repo"*
- *"Create an issue for the login bug — users can't reset their password"*
- *"What merged this week in my-repo?"*
- *"Show me the details on issue #42"*

---

## Architecture

```
Slack ──▶ Slack Bot (Python/Bolt)
               │
               ▼
         Claude API (claude-sonnet-4-6)
               │  tool calls
               ▼
         MCP Server (Python/FastMCP)
               │
               ▼
         GitHub API (PyGithub)
```

The MCP server exposes GitHub as a set of tools. Claude decides which tools to call based on what the user asks, executes them via the MCP protocol, and returns a clean natural language response to Slack.

---

## Available Tools

| Tool | Description |
|---|---|
| `list_repos` | List all repos accessible to your token |
| `list_issues` | List open/closed issues for a repo |
| `get_issue` | Get full details and comments on an issue |
| `create_issue` | Create a new issue |
| `close_issue` | Close an issue |
| `list_pull_requests` | List open/closed PRs |
| `get_pull_request` | Get PR details including changed files |
| `summarize_recent_activity` | Summary of commits, issues, and merged PRs |

---

## Local Setup

**1. Clone the repo**
```bash
git clone https://github.com/your-username/orbit.git
cd orbit
```

**2. Install dependencies**
```bash
pip install -r requirements.txt
```

**3. Set up environment variables**
```bash
cp .env.example .env
```
Fill in your `.env`:
```
GITHUB_TOKEN=your_fine_grained_github_token
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
ANTHROPIC_API_KEY=sk-ant-...
```

**4. Create your Slack app**

Go to [api.slack.com/apps](https://api.slack.com/apps) and create a new app. You'll need:
- Socket Mode enabled (generates your `xapp-` token)
- Bot scopes: `app_mentions:read`, `chat:write`, `im:history`, `im:write`, `channels:history`
- Event subscriptions: `app_mention`, `message.im`

**5. Run**
```bash
python slack_bot/bot.py
```

---

## Deploy to Railway

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new/template)

1. Fork this repo
2. Create a new Railway project from your fork
3. Add the four environment variables in Railway's dashboard
4. Set the start command to: `python slack_bot/bot.py`

---

## GitHub Token Permissions

Create a [fine-grained personal access token](https://github.com/settings/personal-access-tokens/new) with:
- **Issues**: Read and Write
- **Pull requests**: Read
- **Contents**: Read (for commit history)

Scope it to only the repositories you want Orbit to access.

---

## Tech Stack

- [Slack Bolt for Python](https://slack.dev/bolt-python/)
- [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python)
- [FastMCP](https://github.com/jlowin/fastmcp)
- [PyGithub](https://github.com/PyGithub/PyGithub)
