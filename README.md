# agmsg-mcp

A small Model Context Protocol (MCP) bridge for [agmsg](https://github.com/fujibee/agmsg).
It lets an MCP host read agmsg teams/messages, send messages to CLI agents, and optionally
wait for an agent reply within one MCP tool call.

This project deliberately uses agmsg's documented external-consumer boundary:

- reads: `scripts/api.sh`
- writes: `scripts/send.sh` and `scripts/join.sh`

It does **not** read or write agmsg's SQLite database or team config files directly.

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

Streamable HTTP is the default:

```bash
uv run agmsg-mcp
```

The MCP endpoint is then:

```text
http://127.0.0.1:8000/mcp
```

For stdio clients:

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

Start the server, then point MCP Inspector at:

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

## ChatGPT deployment note

ChatGPT connects to a **remote** MCP endpoint, not directly to localhost. For a server running on a
developer machine or private network, use an approved secure tunnel/private access mechanism rather
than exposing the MCP port unauthenticated to the public internet.

The bridge intentionally ships without a public-network authentication layer in this first version.
Keep the default bind address (`127.0.0.1`) unless you have put an authenticated access layer in front
of it.

## Security model

- no `shell=True`; user-controlled values are passed as separate subprocess arguments
- no direct SQLite/config-file access
- agmsg itself validates team/agent membership on writes
- message-history `limit` is capped at 1000
- `agmsg_ask_agent` timeout is capped at 240 seconds
- bridge identity registration uses agmsg's built-in non-spawnable `agmsg-app` type
- public unauthenticated exposure is not supported by default

## Development

Run the unit tests:

```bash
uv run python -m unittest discover -s tests -v
```

The tests cover JSONL parsing, bridge registration, subprocess argument isolation, bounds checking, and correlated replies.
