from __future__ import annotations

import argparse
import asyncio
import os
from typing import Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from .client import AgmsgClient


mcp = MCPServer("agmsg-mcp")

_READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
_WRITE_ADDITIVE = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=True,
)


def _client() -> AgmsgClient:
    return AgmsgClient()


@mcp.tool(
    name="agmsg_list_teams",
    description="List agmsg teams visible to this agmsg installation.",
    annotations=_READ_ONLY,
)
def agmsg_list_teams() -> dict[str, Any]:
    return {"status": "ok", "teams": _client().list_teams()}


@mcp.tool(
    name="agmsg_list_members",
    description="List registered members of an agmsg team, including their runtime types and project.",
    annotations=_READ_ONLY,
)
def agmsg_list_members(team: str) -> dict[str, Any]:
    return {"status": "ok", "team": team, "members": _client().list_members(team)}


@mcp.tool(
    name="agmsg_get_messages",
    description=(
        "Read recent agmsg messages for a team. Optionally filter to messages sent from or to one agent. "
        "Results are oldest-first within the selected recent page."
    ),
    annotations=_READ_ONLY,
)
def agmsg_get_messages(
    team: str,
    agent: str | None = None,
    limit: int = 30,
    before_id: str | None = None,
) -> dict[str, Any]:
    messages = _client().get_messages(team, agent=agent, limit=limit, before_id=before_id)
    return {"status": "ok", "team": team, "messages": messages}


@mcp.tool(
    name="agmsg_send_message",
    description=(
        "Send a message from one registered agmsg agent to another registered agent. "
        "This writes a new message to agmsg and may trigger delivery to the target agent."
    ),
    annotations=_WRITE_ADDITIVE,
)
def agmsg_send_message(team: str, from_agent: str, to_agent: str, body: str) -> dict[str, Any]:
    return _client().send_message(team, from_agent, to_agent, body)


@mcp.tool(
    name="agmsg_ask_agent",
    description=(
        "Send a task/question to a registered agmsg agent and wait for its correlated direct reply. "
        "Use this when the caller needs another agent's answer within the current MCP tool call. "
        "The target agent must already be running and receiving agmsg messages."
    ),
    annotations=_WRITE_ADDITIVE,
)
async def agmsg_ask_agent(
    team: str,
    from_agent: str,
    to_agent: str,
    prompt: str,
    timeout_seconds: float = 90.0,
    poll_interval_seconds: float = 2.0,
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _client().ask_agent,
        team,
        from_agent,
        to_agent,
        prompt,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="MCP bridge for agmsg")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=os.getenv("MCP_TRANSPORT", "streamable-http"),
    )
    parser.add_argument("--host", default=os.getenv("MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MCP_PORT", "8000")))
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return

    mcp.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        stateless_http=True,
        json_response=True,
    )


if __name__ == "__main__":
    main()
