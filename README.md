# agmsg-mcp

A small Model Context Protocol (MCP) bridge for [agmsg](https://github.com/fujibee/agmsg).
It lets an MCP host read agmsg teams/messages, send messages to CLI agents, and optionally
wait for an agent reply within one MCP tool call.

This project deliberately uses agmsg's documented external-consumer boundary:

- reads: `scripts/api.sh`
- writes: `scripts/send.sh` and `scripts/join.sh`

It does **not** read or write agmsg's SQLite database or team config files directly.

## Recommended ChatGPT setup: Secure MCP Tunnel + stdio

For ChatGPT, the recommended deployment is to keep `agmsg-mcp` private on the same machine as
agmsg and connect it through OpenAI Secure MCP Tunnel using the MCP `stdio` transport.

```text
ChatGPT
   |
   v
OpenAI Secure MCP Tunnel
   |
   | outbound HTTPS connection from your machine
   v
tunnel-client
   |
   | stdio
   v
agmsg-mcp
   |
   v
agmsg
   +-- Codex
   +-- Claude Code
   +-- Gemini CLI
```

This does **not** require an inbound firewall rule, router port-forward, or a publicly reachable
MCP URL. `tunnel-client` runs inside the network that can already reach `agmsg-mcp`, opens an
outbound HTTPS path to OpenAI, and starts/communicates with the MCP server locally over stdio.

OpenAI documentation:

- Secure MCP Tunnel: https://developers.openai.com/api/docs/guides/secure-mcp-tunnels
- ChatGPT developer mode / MCP apps: https://help.openai.com/en/articles/12584461-developer-mode-and-full-mcp-connectors-in-chatgpt

> ChatGPT cannot connect directly to a localhost MCP server. Use Secure MCP Tunnel for a private
> developer-machine/on-premises deployment. Write/modify tools also require a ChatGPT plan/workspace
> that supports Full MCP; consult the current OpenAI documentation because availability can change.

### Windows / PowerShell quickstart

#### 1. Install and prepare agmsg-mcp

```powershell
git clone https://github.com/ishiishikou/agmsg-mcp.git
cd agmsg-mcp
uv sync
```

agmsg must be installed on the same machine. By default this bridge looks for:

```text
~/.agents/skills/agmsg/scripts
```

If necessary, point to the actual scripts directory explicitly:

```powershell
$env:AGMSG_SCRIPTS_DIR = "$HOME\.agents\skills\agmsg\scripts"
```

You can verify that the MCP process starts in stdio mode:

```powershell
uv run agmsg-mcp --transport stdio
```

Stop it after confirming that it starts; `tunnel-client` will start it again as its local MCP command.

#### 2. Create an OpenAI Secure MCP Tunnel

In OpenAI Platform tunnel settings, create a tunnel and note the returned `tunnel_id`.
Associate the tunnel with both:

- the Platform organization that owns/manages the tunnel
- the ChatGPT workspace that will create/use the custom app

OpenAI currently documents these Platform permissions:

- create/edit tunnel: **Tunnels Read + Manage**
- run `tunnel-client` or select the tunnel in ChatGPT: **Tunnels Read + Use**

#### 3. Install tunnel-client

Download the current `tunnel-client` from OpenAI Platform tunnel settings or the latest public
OpenAI release. Check the installed binary first:

```powershell
tunnel-client help quickstart
```

Set the runtime API key used by the tunnel client:

```powershell
$env:CONTROL_PLANE_API_KEY = "sk-..."
```

Use a runtime API key with only the permissions required for the tunnel environment; do not commit
it to this repository.

#### 4. Create a stdio tunnel profile for agmsg-mcp

Run these commands from the `agmsg-mcp` repository directory so `uv run agmsg-mcp` resolves the
local project correctly:

```powershell
tunnel-client init `
  --sample sample_mcp_stdio_local `
  --profile agmsg-mcp `
  --tunnel-id tunnel_0123456789abcdef0123456789abcdef `
  --mcp-command "uv run agmsg-mcp --transport stdio"
```

Validate the profile:

```powershell
tunnel-client doctor --profile agmsg-mcp --explain
```

Then run the tunnel client:

```powershell
tunnel-client run --profile agmsg-mcp
```

Keep this process running while ChatGPT scans or invokes the MCP tools. If the tunnel stops,
ChatGPT tool discovery/calls through that tunnel stop working until it reconnects.

#### 5. Create the ChatGPT custom app

In ChatGPT Web with developer mode enabled:

1. Create a developer-mode custom app.
2. Under **Connection**, choose **Tunnel**.
3. Select the tunnel from the list, or paste its `tunnel_id`.
4. Scan/refresh the MCP tools.
5. Review the detected actions before enabling/publishing the app in the workspace.

The expected tools are:

```text
agmsg_list_teams
agmsg_list_members
agmsg_register_bridge
agmsg_get_messages
agmsg_send_message
agmsg_ask_agent
```

#### 6. First end-to-end smoke test

Start with read-only calls:

1. Call `agmsg_list_teams`.
2. Call `agmsg_list_members` for an existing team.

Then register the ChatGPT/MCP-side identity once for that team:

```text
agmsg_register_bridge(team="your-team", agent_name="chatgpt")
```

After a target CLI agent is registered and running, test a write:

```text
agmsg_send_message(
  team="your-team",
  from_agent="chatgpt",
  to_agent="codex",
  body="Hello from ChatGPT via agmsg-mcp"
)
```

Finally, test the request/reply flow:

```text
agmsg_ask_agent(
  team="your-team",
  from_agent="chatgpt",
  to_agent="codex",
  prompt="Reply with a short acknowledgement."
)
```

`agmsg_ask_agent` requires the target agent to already be running and receiving agmsg messages.
It does not spawn the target CLI.

### Secure Tunnel troubleshooting

If the tunnel does not appear in ChatGPT:

- confirm the tunnel is associated with the target **ChatGPT workspace**, not only the Platform organization
- confirm the app creator has **Tunnels Read + Use**
- keep `tunnel-client run --profile agmsg-mcp` running
- rerun:

```powershell
tunnel-client doctor --profile agmsg-mcp --explain
```

`tunnel-client` itself does not need inbound internet access. The host needs outbound HTTPS access
to OpenAI and local access to the configured MCP command/server.

## Tools

| Tool | Effect |
|---|---|
| `agmsg_list_teams` | Read-only: list teams |
| `agmsg_list_members` | Read-only: list registered agents in a team |
| `agmsg_register_bridge` | Write/idempotent: register the MCP-side identity as agmsg `agmsg-app` |
| `agmsg_get_messages` | Read-only: read recent messages, optionally filtered by agent |
| `agmsg_send_message` | Write: send a message between registered agents |
| `agmsg_ask_agent` | Write + wait: send a correlated request and wait for a direct reply |

Read-only tools publish MCP `readOnlyHint=true`. Bridge registration is an idempotent write;
send/ask are marked as additive, non-idempotent write operations.

## Requirements

- Python 3.10+
- agmsg installed on the same machine as this MCP server
- Bash available to execute agmsg's scripts
- the recipient used by `send` / `ask` must already be registered in the agmsg team
- the MCP-side sender can be registered with `agmsg_register_bridge` (defaults to the name `chatgpt`)

By default the bridge looks for agmsg at:

```text
~/.agents/skills/agmsg/scripts
```

If your agmsg command/install name is different, set `AGMSG_COMMAND_NAME`, or point directly
to the scripts directory with `AGMSG_SCRIPTS_DIR`.

## Install

Using `uv`:

```bash
uv sync
```

Or install as a package:

```bash
pip install -e .
```

## Run locally

For local MCP development, Streamable HTTP remains available:

```bash
uv run agmsg-mcp
```

The local endpoint is:

```text
http://127.0.0.1:8000/mcp
```

Do not expose this unauthenticated endpoint directly to the public internet.

For stdio clients, including the recommended Secure MCP Tunnel configuration for ChatGPT:

```bash
uv run agmsg-mcp --transport stdio
```

Useful environment variables:

```bash
export AGMSG_SCRIPTS_DIR="$HOME/.agents/skills/agmsg/scripts"
export AGMSG_COMMAND_TIMEOUT_SECONDS=15
export MCP_HOST=127.0.0.1
export MCP_PORT=8000
```

## Test with MCP Inspector

For local development, start the HTTP server and point MCP Inspector at:

```text
http://127.0.0.1:8000/mcp
```

Basic sequence:

1. call `agmsg_list_teams`
2. call `agmsg_list_members` for a team
3. call `agmsg_register_bridge` for that team (the default identity is `chatgpt`)
4. call `agmsg_get_messages`
5. call `agmsg_send_message` with `from_agent=chatgpt`
6. once the target agent is running and receiving agmsg messages, try `agmsg_ask_agent` with `from_agent=chatgpt`

## MCP-side identity

agmsg validates both the sender and recipient of a normal message. The bridge therefore cannot simply
invent an unregistered `chatgpt` sender. Current agmsg includes the built-in `agmsg-app` type for an
application-owned, non-spawnable identity. `agmsg_register_bridge` calls agmsg's documented `join.sh`
interface to register the MCP-side identity using that type.

By default:

```text
agent name: chatgpt
type:       agmsg-app
project:    AGMSG_MCP_PROJECT, or the MCP server's current working directory
```

The operation is safe to call again for the same registration. You can choose another `agent_name` or
explicit `project` if needed.

## `agmsg_ask_agent` correlation

agmsg messages currently do not expose a thread/reply identifier. To avoid treating an unrelated
agent message as the answer, `agmsg_ask_agent` adds a unique correlation token to the request and
asks the target agent to include that token in its direct reply. The bridge accepts only a new
message from the target agent to the sender that contains the token.

If no correlated reply arrives before the timeout, the tool returns `status=timeout` and includes
any new direct replies that arrived without the token as `candidate_replies`.

This means `agmsg_ask_agent` requires the target agent to be running and configured to receive
agmsg messages. It does not spawn or drive the target CLI itself.

## Security model

- no `shell=True`; user-controlled values are passed as separate subprocess arguments
- no direct SQLite/config-file access
- agmsg itself validates team/agent membership on writes
- message-history `limit` is capped at 1000
- `agmsg_ask_agent` timeout is capped at 240 seconds
- bridge identity registration uses agmsg's built-in non-spawnable `agmsg-app` type
- HTTP binds to `127.0.0.1` by default
- public unauthenticated exposure is not supported by default
- for ChatGPT, Secure MCP Tunnel + stdio is preferred over public HTTP exposure

## Development

Run the unit tests:

```bash
uv run python -m unittest discover -s tests -v
```

The tests cover JSONL parsing, bridge registration, subprocess argument isolation, bounds checking, and correlated replies.
