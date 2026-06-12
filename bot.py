"""
Relay — a Slack bot that lets you interact with GitHub in natural language.

Receives Slack messages, runs them through Claude with a set of GitHub tools
exposed by a local MCP server, and replies with the result.
"""
import os
import sys
import json
import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("relay")

app = AsyncApp(token=os.environ["SLACK_BOT_TOKEN"])
client = Anthropic()

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 2048
MCP_SERVER_PATH = os.path.join(os.path.dirname(__file__), "server.py")

SYSTEM_PROMPT = """You are Relay, an AI assistant that helps developers interact with GitHub directly from Slack.

You have access to tools that let you:
- List repos, issues, and pull requests
- Get details on specific issues and PRs
- Create and close issues
- Summarize recent repository activity

When a user asks about their GitHub repos/issues/PRs, use the appropriate tools to fetch real data and give a clear, concise response.
Format responses for Slack — use *bold* for emphasis, bullet points for lists, and keep things scannable.
If a repo name is ambiguous, ask for clarification before proceeding.
Always include relevant GitHub URLs so users can click through."""


# --- MCP communication -------------------------------------------------------
# Each call spawns the MCP server, performs the JSON-RPC handshake, sends one
# request, and reads the response. Requests are tagged with an id so we can
# distinguish the tool response from the initialize acknowledgment.

INIT_MSG = json.dumps({
    "jsonrpc": "2.0", "id": 0, "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "relay-slack-bot", "version": "1.0"},
    },
}) + "\n"

INITIALIZED_NOTIF = json.dumps({
    "jsonrpc": "2.0", "method": "notifications/initialized", "params": {}
}) + "\n"

TOOLS_LIST_ID = 1
TOOL_CALL_ID = 2


async def _run_mcp(request: dict, timeout: int = 30) -> list[dict]:
    """Spawn the MCP server, run the init handshake + one request, return parsed responses."""
    payload = INIT_MSG + INITIALIZED_NOTIF + json.dumps(request) + "\n"
    proc = await asyncio.create_subprocess_exec(
        sys.executable, MCP_SERVER_PATH,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ},
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(payload.encode()), timeout=timeout)

    parsed = []
    for line in stdout.decode().splitlines():
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return parsed


async def get_mcp_tools() -> list[dict]:
    """Return the MCP server's tools in Anthropic tool-schema format."""
    responses = await _run_mcp(
        {"jsonrpc": "2.0", "id": TOOLS_LIST_ID, "method": "tools/list", "params": {}},
        timeout=10,
    )
    for data in responses:
        if data.get("id") == TOOLS_LIST_ID and "tools" in data.get("result", {}):
            return [
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "input_schema": t.get("inputSchema", {"type": "object", "properties": {}}),
                }
                for t in data["result"]["tools"]
            ]
    return []


async def call_mcp_tool(tool_name: str, tool_input: dict) -> str:
    """Call a single tool on the MCP server and return its text output."""
    responses = await _run_mcp({
        "jsonrpc": "2.0", "id": TOOL_CALL_ID, "method": "tools/call",
        "params": {"name": tool_name, "arguments": tool_input},
    })
    for data in responses:
        if data.get("id") == TOOL_CALL_ID and "result" in data:
            content = data["result"].get("content", [])
            return "\n".join(
                block.get("text", "") for block in content if block.get("type") == "text"
            )
    return "Error: no response from MCP server."


# --- Agent loop --------------------------------------------------------------

async def run_agent(user_message: str) -> str:
    """Run Claude in a tool-use loop until it produces a final answer."""
    tools = await get_mcp_tools()
    log.info("Loaded %d tools", len(tools))
    messages = [{"role": "user", "content": user_message}]

    while True:
        response = await asyncio.to_thread(
            client.messages.create,
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text
            return "Done."

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    log.info("Calling tool %s(%s)", block.name, block.input)
                    result = await call_mcp_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "user", "content": tool_results})
        else:
            log.warning("Unexpected stop_reason: %s", response.stop_reason)
            return "Something went wrong — unexpected response from Claude."


# --- Slack handlers ----------------------------------------------------------

async def _respond(user_message: str, say):
    """Shared handler logic: acknowledge, run the agent, reply (or report errors)."""
    if not user_message:
        return
    await say("_On it..._")
    try:
        reply = await run_agent(user_message)
    except Exception:
        log.exception("Agent failed")
        reply = "⚠️ Something went wrong while handling that. Check the server logs for details."
    await say(reply)


@app.event("app_mention")
async def handle_mention(event, say):
    """Respond when the bot is @mentioned in a channel."""
    text = event.get("text", "")
    # Strip the leading bot mention, e.g. "<@U123> list my repos" -> "list my repos"
    if "<@" in text:
        text = text.split(">", 1)[-1]
    await _respond(text.strip(), say)


@app.event("message")
async def handle_dm(event, say):
    """Respond to direct messages, ignoring messages from bots."""
    if event.get("channel_type") != "im" or event.get("bot_id"):
        return
    await _respond(event.get("text", "").strip(), say)


async def main():
    handler = AsyncSocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    log.info("⚡ Relay is running...")
    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(main())