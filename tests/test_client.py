from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agmsg_mcp.client import AgmsgClient, AgmsgConfig, AgmsgError


class AgmsgClientTests(unittest.TestCase):
    def make_client(self, root: Path) -> AgmsgClient:
        return AgmsgClient(AgmsgConfig(scripts_dir=root, command_timeout_seconds=2))

    def test_list_teams_parses_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "api.sh"
            script.write_text(
                "#!/usr/bin/env bash\nprintf '%s\\n' '{\"name\":\"alpha\"}' '{\"name\":\"beta\"}'\n",
                encoding="utf-8",
            )
            client = self.make_client(root)
            self.assertEqual(client.list_teams(), [{"name": "alpha"}, {"name": "beta"}])

    def test_send_message_passes_arguments_without_shell_interpolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_file = root / "args.txt"
            script = root / "send.sh"
            script.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$@\" > \"$ARGS_OUT\"\n"
                "printf 'sent\\n'\n",
                encoding="utf-8",
            )
            client = self.make_client(root)
            with patch.dict("os.environ", {"ARGS_OUT": str(output_file)}):
                result = client.send_message("team", "chatgpt", "codex", "hello; echo unsafe")
            self.assertEqual(result["status"], "sent")
            self.assertEqual(
                output_file.read_text(encoding="utf-8").splitlines(),
                ["team", "chatgpt", "codex", "hello; echo unsafe"],
            )

    def test_get_messages_rejects_excessive_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.make_client(Path(tmp))
            with self.assertRaises(AgmsgError):
                client.get_messages("team", limit=1001)

    def test_ask_agent_accepts_only_correlated_reply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            client = self.make_client(Path(tmp))
            baseline = [{"id": "1", "from": "codex", "to": "chatgpt", "body": "old"}]
            state = {"calls": 0, "sent": ""}

            def fake_get_messages(*args, **kwargs):
                state["calls"] += 1
                if state["calls"] == 1:
                    return baseline
                token = state["sent"].split("[agmsg-mcp-reply:", 1)[1].split("]", 1)[0]
                return baseline + [
                    {"id": "2", "from": "codex", "to": "chatgpt", "body": "unrelated"},
                    {
                        "id": "3",
                        "from": "codex",
                        "to": "chatgpt",
                        "body": f"review complete [agmsg-mcp-reply:{token}]",
                    },
                ]

            def fake_send_message(team, from_agent, to_agent, body):
                state["sent"] = body
                return {"status": "sent"}

            with patch.object(client, "get_messages", side_effect=fake_get_messages), patch.object(
                client, "send_message", side_effect=fake_send_message
            ):
                result = client.ask_agent(
                    "team",
                    "chatgpt",
                    "codex",
                    "review this",
                    timeout_seconds=1,
                    poll_interval_seconds=0.25,
                )

            self.assertEqual(result["status"], "replied")
            self.assertEqual(result["reply"]["body"], "review complete")


if __name__ == "__main__":
    unittest.main()
