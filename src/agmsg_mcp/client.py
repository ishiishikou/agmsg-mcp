from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class AgmsgError(RuntimeError):
    """Raised when an agmsg script call fails or returns invalid data."""


@dataclass(frozen=True)
class AgmsgConfig:
    scripts_dir: Path
    command_timeout_seconds: float = 15.0

    @classmethod
    def from_env(cls) -> "AgmsgConfig":
        explicit = os.getenv("AGMSG_SCRIPTS_DIR")
        if explicit:
            scripts_dir = Path(explicit).expanduser()
        else:
            command_name = os.getenv("AGMSG_COMMAND_NAME", "agmsg")
            scripts_dir = Path.home() / ".agents" / "skills" / command_name / "scripts"

        raw_timeout = os.getenv("AGMSG_COMMAND_TIMEOUT_SECONDS", "15")
        try:
            timeout = float(raw_timeout)
        except ValueError as exc:
            raise AgmsgError("AGMSG_COMMAND_TIMEOUT_SECONDS must be numeric") from exc
        if timeout <= 0:
            raise AgmsgError("AGMSG_COMMAND_TIMEOUT_SECONDS must be greater than zero")

        return cls(scripts_dir=scripts_dir, command_timeout_seconds=timeout)


class AgmsgClient:
    """Thin wrapper around agmsg's documented scripts interface.

    Reads go through scripts/api.sh and writes go through agmsg's documented
    write scripts. The database and team config files are deliberately never
    read or written directly.
    """

    def __init__(self, config: AgmsgConfig | None = None) -> None:
        self.config = config or AgmsgConfig.from_env()

    def _script(self, name: str) -> Path:
        path = (self.config.scripts_dir / name).resolve()
        scripts_dir = self.config.scripts_dir.resolve()
        if path.parent != scripts_dir:
            raise AgmsgError(f"Refusing script outside AGMSG_SCRIPTS_DIR: {path}")
        if not path.is_file():
            raise AgmsgError(
                f"agmsg script not found: {path}. Set AGMSG_SCRIPTS_DIR to the agmsg scripts directory."
            )
        return path

    def _run(self, script_name: str, *args: str) -> str:
        script = self._script(script_name)
        try:
            completed = subprocess.run(
                ["bash", str(script), *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.config.command_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise AgmsgError(
                f"agmsg command timed out after {self.config.command_timeout_seconds:g}s: {script_name}"
            ) from exc
        except OSError as exc:
            raise AgmsgError(f"Failed to execute agmsg command {script_name}: {exc}") from exc

        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
            raise AgmsgError(f"{script_name} failed with exit code {completed.returncode}: {detail}")
        return completed.stdout.strip()

    @staticmethod
    def _parse_jsonl(output: str) -> list[dict[str, Any]]:
        if not output:
            return []
        records: list[dict[str, Any]] = []
        for line_number, line in enumerate(output.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AgmsgError(f"Invalid JSONL from agmsg on line {line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise AgmsgError(f"Expected a JSON object from agmsg on line {line_number}")
            records.append(value)
        return records

    def list_teams(self) -> list[dict[str, Any]]:
        output = self._run("api.sh", "get", "teams")
        return self._parse_jsonl(output)

    def register_bridge(
        self,
        team: str,
        *,
        agent_name: str = "chatgpt",
        project: str | None = None,
    ) -> dict[str, Any]:
        """Register the MCP-side identity using agmsg's built-in agmsg-app type."""
        if not agent_name.strip():
            raise AgmsgError("agent_name must not be empty")
        project_path = Path(
            project or os.getenv("AGMSG_MCP_PROJECT") or os.getcwd()
        ).expanduser().resolve()
        output = self._run("join.sh", team, agent_name, "agmsg-app", str(project_path))
        return {
            "status": "registered",
            "team": team,
            "agent": agent_name,
            "type": "agmsg-app",
            "project": str(project_path),
            "agmsg_output": output,
        }

    def list_members(self, team: str) -> list[dict[str, Any]]:
        output = self._run("api.sh", "get", "teams", team, "members")
        return self._parse_jsonl(output)

    def get_messages(
        self,
        team: str,
        *,
        agent: str | None = None,
        limit: int = 30,
        before_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if limit < 1 or limit > 1000:
            raise AgmsgError("limit must be between 1 and 1000")
        args = ["get", "teams", team, "messages", "--limit", str(limit)]
        if agent:
            args.extend(["--agent", agent])
        if before_id:
            args.extend(["--before-id", before_id])
        output = self._run("api.sh", *args)
        return self._parse_jsonl(output)

    def send_message(self, team: str, from_agent: str, to_agent: str, body: str) -> dict[str, Any]:
        if not body.strip():
            raise AgmsgError("body must not be empty")
        output = self._run("send.sh", team, from_agent, to_agent, body)
        return {
            "status": "sent",
            "team": team,
            "from": from_agent,
            "to": to_agent,
            "message": body,
            "agmsg_output": output,
        }

    def ask_agent(
        self,
        team: str,
        from_agent: str,
        to_agent: str,
        prompt: str,
        *,
        timeout_seconds: float = 90.0,
        poll_interval_seconds: float = 2.0,
    ) -> dict[str, Any]:
        """Send a request and wait for a correlated direct reply.

        agmsg does not currently expose a thread/reply id, so the bridge adds a
        unique textual correlation token and asks the target agent to echo it.
        Only a new direct reply from ``to_agent`` to ``from_agent`` containing
        that token is accepted as the correlated response.
        """
        if not prompt.strip():
            raise AgmsgError("prompt must not be empty")
        if timeout_seconds < 1 or timeout_seconds > 240:
            raise AgmsgError("timeout_seconds must be between 1 and 240")
        if poll_interval_seconds < 0.25 or poll_interval_seconds > 10:
            raise AgmsgError("poll_interval_seconds must be between 0.25 and 10")

        baseline = self.get_messages(team, agent=from_agent, limit=500)
        baseline_ids = {str(m.get("id")) for m in baseline if m.get("id") is not None}

        request_id = uuid.uuid4().hex
        token = f"[agmsg-mcp-reply:{request_id}]"
        bridged_prompt = (
            f"{prompt.rstrip()}\n\n"
            "Reply directly to the sender via agmsg when complete. "
            f"Include this correlation token exactly once in your reply: {token}"
        )
        self.send_message(team, from_agent, to_agent, bridged_prompt)

        deadline = time.monotonic() + timeout_seconds
        candidate_replies: list[dict[str, Any]] = []
        seen_candidates: set[str] = set()

        while time.monotonic() < deadline:
            messages = self.get_messages(team, agent=from_agent, limit=500)
            for message in messages:
                message_id = str(message.get("id", ""))
                if not message_id or message_id in baseline_ids:
                    continue
                if message.get("from") != to_agent or message.get("to") != from_agent:
                    continue

                body = str(message.get("body", ""))
                if token in body:
                    clean_body = body.replace(token, "").strip()
                    response = dict(message)
                    response["body"] = clean_body
                    return {
                        "status": "replied",
                        "request_id": request_id,
                        "team": team,
                        "from": from_agent,
                        "to": to_agent,
                        "reply": response,
                    }

                if message_id not in seen_candidates:
                    candidate_replies.append(message)
                    seen_candidates.add(message_id)

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(poll_interval_seconds, remaining))

        return {
            "status": "timeout",
            "request_id": request_id,
            "team": team,
            "from": from_agent,
            "to": to_agent,
            "timeout_seconds": timeout_seconds,
            "candidate_replies": candidate_replies,
            "note": (
                "No correlated reply arrived before the timeout. The target agent must be running "
                "and configured to receive agmsg messages. candidate_replies contains any new direct "
                "replies that did not echo the correlation token."
            ),
        }
