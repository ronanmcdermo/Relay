import os
import json
import asyncio
import subprocess
from dotenv import load_dotenv
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
import anthropic
from anthropic import Anthropic

load_dotenv()

app = AsyncApp(token=os.environ["SLACK_BOT_TOKEN"])
client = Anthropic()

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

MCP_SERVER_PATH = os.path.join(os.path.dirname(__file__), "../mcp_server/server.py")


INIT_MSG = json.dumps({
    "jsonrpc": "2.0", "id": 0, "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "relay-slack-bot", "version": "1.0"},
    },
}) + "\n"


def _run_mcp(request: dict, timeout: int = 30) -> list[dict]:
    """Send a request to the MCP server (with init handshake) and return all parsed response lines."""
    payload = INIT_MSG + json.dumps(request) + "\n"
    result = subprocess.run(
        ["python", MCP_SERVER_PATH],
        input=payload,
        capture_output=True, text=True, timeout=timeout,
        env={**os.environ}
    )
    parsed = []
    for line in result.stdout.splitlines():
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return parsed


def get_mcp_tools() -> list[dict]:
    """Query the MCP server for its available tools."""
    responses = _run_mcp({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}, timeout=10)
    for data in responses:
        if "result" in data and "tools" in data.get("result", {}):
            return [
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "input_schema": t.get("inputSchema", {"type": "object", "properties": {}}),
                }
                for t in data["result"]["tools"]
            ]
    return []


def call_mcp_tool(tool_name: str, tool_input: dict) -> str:
    """Call a tool on the MCP server and return the result."""
    responses = _run_mcp({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": tool_name, "arguments": tool_input},
    })
    for data in responses:
        if "result" in data:
            content = data["result"].get("content", [])
            return "\n".join(
                block.get("text", "") for block in content if block.get("type") == "text"
            )
    return "Error: no response from MCP server."


async def run_agent(user_message: str) -> str:
    """Run the Claude agent loop with MCP tools."""
    tools = get_mcp_tools()
    messages = [{"role": "user", "content": user_message}]

    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        )

        # If Claude is done, return the final text response
        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text
            return "Done."

        # If Claude wants to use tools, execute them and feed results back
        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = call_mcp_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
            messages.append({"role": "user", "content": tool_results})
        else:
            # Unexpected stop reason
            return "Something went wrong — unexpected response from Claude."


@app.event("app_mention")
async def handle_mention(event, say):
    """Respond when @Relay is mentioned in a channel."""
    user_message = event["text"]
    # Strip the bot mention from the message
    if "<@" in user_message:
        user_message = user_message.split(">", 1)[-1].strip()

    await say(f"_On it..._")
    response = await asyncio.to_thread(run_agent, user_message)
    await say(response)


@app.event("message")
async def handle_dm(event, say):
    """Respond to direct messages."""
    if event.get("channel_type") != "im":
        return
    if event.get("bot_id"):
        return  # ignore messages from bots

    user_message = event.get("text", "").strip()
    if not user_message:
        return

    await say("_On it..._")
    response = await asyncio.to_thread(run_agent, user_message)
    await say(response)


async def main():
    handler = AsyncSocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    print("⚡ Relay is running...")
    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(main())
