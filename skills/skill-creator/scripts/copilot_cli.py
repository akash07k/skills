"""Shared non-interactive Copilot CLI invocation and response checks."""

import json
import shutil
import subprocess
from functools import lru_cache


def copilot_command(model: str | None, tools: tuple[str, ...] = ()) -> list[str]:
    executable = shutil.which("copilot")
    if executable is None:
        raise FileNotFoundError("Copilot CLI was not found on PATH. Install Copilot CLI and run copilot login.")
    command = [
        executable, "--output-format", "json", "--stream", "on",
        "--no-auto-update", "--no-ask-user",
        "--disable-builtin-mcps", "--available-tools", *(tools or ("none",)),
    ]
    if "skill" in tools:
        command.extend(["--allow-tool", "skill"])
    if model:
        command.extend(["--model", model])
    return command


@lru_cache(maxsize=1)
def copilot_version() -> str | None:
    """Return the installed CLI version without making evaluation depend on it."""
    executable = shutil.which("copilot")
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    output = (result.stdout or result.stderr).strip()
    return output.splitlines()[0] if output else None


def check_event(event: dict) -> None:
    if event.get("type") == "session.error":
        raise RuntimeError(f"Copilot reported an error: {json.dumps(event.get('data', {}))}")
    if event.get("type") == "result" and event.get("exitCode") != 0:
        raise RuntimeError(f"Copilot did not complete successfully: {json.dumps(event)}")


def response_text(output: str) -> str:
    """Require a successful terminal result, not just a partial assistant message."""
    content = None
    completed = False
    for line in output.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise RuntimeError("Copilot returned invalid JSONL output") from error
        if not isinstance(event, dict):
            raise RuntimeError("Copilot returned a non-object JSONL event")
        check_event(event)
        data = event.get("data", {})
        if event.get("type") == "assistant.message" and not data.get("parentToolCallId"):
            content = data.get("content")
        elif event.get("type") == "result":
            completed = True
    if not completed:
        raise RuntimeError("Copilot ended without a terminal result (incomplete stream)")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Copilot returned no description text")
    return content
