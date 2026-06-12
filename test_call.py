import os
import json
import subprocess
import sys
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

MCP_SERVER_PATH = os.path.join(os.path.dirname(__file__), "server.py")

INIT_MSG = json.dumps({
    "jsonrpc": "2.0", "id": 0, "method": "initialize",
    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
               "clientInfo": {"name": "relay-test", "version": "1.0"}},
}) + "\n"
INITIALIZED_NOTIF = json.dumps({
    "jsonrpc": "2.0", "method": "notifications/initialized", "params": {}
}) + "\n"


def run_mcp(request, timeout=30):
    payload = INIT_MSG + INITIALIZED_NOTIF + json.dumps(request) + "\n"
    result = subprocess.run(
        [sys.executable, MCP_SERVER_PATH],
        input=payload, capture_output=True, text=True, timeout=timeout,
        env={**os.environ},
    )
    print("=== RAW STDERR ===")
    print(result.stderr[:500])
    print("=== PARSED RESPONSES ===")
    for line in result.stdout.splitlines():
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            print("(non-JSON line):", line[:120])


print("Calling list_repos through the MCP subprocess...\n")
for data in run_mcp({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                     "params": {"name": "list_repos", "arguments": {}}}):
    if data.get("id") == 2 and "result" in data:
        content = data["result"].get("content", [])
        text = "\n".join(b.get("text", "") for b in content if b.get("type") == "text")
        print("\n=== list_repos RETURNED ===")
        print(text)