"""Shared non-interactive Copilot CLI invocation and response checks."""

import json
import os
import shutil
import signal
import subprocess
from functools import lru_cache

# Captured at import so cleanup still works when callers patch subprocess.Popen.
_POPEN = subprocess.Popen


def process_group_kwargs() -> dict:
    """Popen options that let kill_process_tree reach every descendant."""
    return {} if os.name == "nt" else {"start_new_session": True}


def kill_process_tree(process: subprocess.Popen) -> None:
    """Kill a child and all of its descendants; never raises.

    Windows uses taskkill /T because Popen.kill only ends the direct child,
    leaving Copilot's own children running. POSIX children must be started
    with process_group_kwargs() so the whole session can be signalled.
    """
    if os.name == "nt":
        if process.poll() is None:
            try:
                killer = _POPEN(
                    ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                try:
                    killer.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    killer.kill()
                    killer.wait()
            except (OSError, subprocess.SubprocessError):
                pass
    else:
        try:
            group = os.getpgid(process.pid)
            if group == process.pid and group != os.getpgrp():
                os.killpg(group, signal.SIGKILL)
        except (OSError, AttributeError):
            pass
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass


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


def isolated_env(root) -> dict:
    """Environment that hides personal skills, plugins and ancestor .agents/skills.

    A throwaway HOME/COPILOT_HOME drops personal skills and plugins; a git root
    at `root` stops Copilot from scanning ancestor directories for project skills.
    Authentication still comes from the OS credential store or token env vars.
    """
    profile = os.path.join(root, ".profile")
    os.makedirs(profile, exist_ok=True)
    if shutil.which("git"):
        _POPEN(["git", "init", "-q", str(root)], stdin=subprocess.DEVNULL,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).wait()
    return dict(os.environ, HOME=profile, USERPROFILE=profile,
                COPILOT_HOME=os.path.join(profile, ".copilot"))


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
