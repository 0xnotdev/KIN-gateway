"""Supervised local command subprocess bridge implementation per §15.7 and §2.2."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

from kin.adapters.base import (
    AdapterActivityEvent,
    AdapterMessage,
    AdapterRequest,
    AdapterResponse,
)
from kin.schemas import AgentCard, MessageKind


class LocalCommandAdapter:
    """Supervised local command subprocess execution bridge."""

    ALLOWED_ENV_VARS: set[str] = {"PATH", "HOME", "USERPROFILE", "LANG", "LC_ALL", "SYSTEMROOT", "TMP", "TEMP"}

    def __init__(self, card: AgentCard):
        self.card = card
        if card.adapter.type != "local_command" and getattr(card.adapter.type, "value", None) != "local_command":
            raise ValueError("LocalCommandAdapter requires a card with adapter.type == 'local_command'.")

    def invoke(self, request: AdapterRequest, vault_key: bytes | None = None) -> AdapterResponse:
        """Execute supervised subprocess command bounded by security constraints."""
        adapter_cfg = self.card.adapter
        cmd_cfg = adapter_cfg.command
        if isinstance(cmd_cfg, str):
            import shlex
            cmd_args = shlex.split(cmd_cfg, posix=(sys.platform != "win32"))
        elif isinstance(cmd_cfg, list):
            cmd_args = cmd_cfg
        else:
            return AdapterResponse(
                events=[AdapterActivityEvent(label="Invalid command configuration")],
                error={"code": "INVALID_COMMAND_CONFIG", "message": "Command must be a string or list of argument strings."},
            )

        if not cmd_args:
            return AdapterResponse(
                events=[AdapterActivityEvent(label="Invalid command configuration")],
                error={"code": "INVALID_COMMAND_CONFIG", "message": "Command cannot be empty."},
            )

        # 1. Re-verify working directory as absolute and traversal-free
        work_dir = Path(adapter_cfg.working_directory).resolve()
        if not work_dir.is_absolute():
            return AdapterResponse(
                events=[AdapterActivityEvent(label="Insecure working directory configuration")],
                error={"code": "INSECURE_WORKING_DIR", "message": "Working directory must be an absolute path."},
            )
        if ".." in adapter_cfg.working_directory:
            return AdapterResponse(
                events=[AdapterActivityEvent(label="Path traversal detected in working directory")],
                error={"code": "PATH_TRAVERSAL_DETECTED", "message": "Path traversal '..' is forbidden in working directory."},
            )

        # 2. Build minimal environment dict (no parent env leakage)
        minimal_env: dict[str, str] = {}
        for k in self.ALLOWED_ENV_VARS:
            if k in os.environ:
                minimal_env[k] = os.environ[k]

        # 3. Timeouts and limits
        max_runtime = float(self.card.boundaries.max_runtime_seconds or 30.0)
        max_bytes = int(self.card.boundaries.max_artifact_bytes or 1_048_576)

        # 4. Invoke via subprocess.Popen(shell=False)
        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP

        try:
            process = subprocess.Popen(
                cmd_args,
                cwd=str(work_dir),
                env=minimal_env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                creationflags=creation_flags,
            )
        except Exception as e:
            return AdapterResponse(
                events=[AdapterActivityEvent(label=f"Failed to spawn process: {e}")],
                error={"code": "PROCESS_SPAWN_FAILED", "message": str(e)},
            )

        # Write request JSON to stdin
        req_json_bytes = json.dumps(request.model_dump(mode="json")).encode("utf-8")

        stdout_bytes = b""
        stderr_bytes = b""
        timed_out = False

        try:
            stdout_bytes, stderr_bytes = process.communicate(input=req_json_bytes, timeout=max_runtime)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._kill_process_tree(process.pid)
            stdout_bytes, stderr_bytes = process.communicate()

        events: list[AdapterActivityEvent] = []

        if timed_out:
            events.append(AdapterActivityEvent(label=f"Process tree killed due to runtime timeout ({max_runtime}s)"))
            return AdapterResponse(
                events=events,
                error={
                    "code": "PROCESS_TIMEOUT_KILLED",
                    "message": f"Local command timed out after {max_runtime}s and process tree was terminated.",
                },
            )

        # Bounded stdout/stderr
        truncated = False
        if len(stdout_bytes) > max_bytes:
            stdout_bytes = stdout_bytes[:max_bytes]
            truncated = True
        if len(stderr_bytes) > max_bytes:
            stderr_bytes = stderr_bytes[:max_bytes]
            truncated = True

        if truncated:
            events.append(AdapterActivityEvent(label=f"Output truncated to max_artifact_bytes ({max_bytes} bytes)"))

        out_text = stdout_bytes.decode("utf-8", errors="replace").strip()

        # Parse JSON response from output if present, or treat stdout as message content
        if out_text.startswith("{") and out_text.endswith("}"):
            try:
                parsed = json.loads(out_text)
                if isinstance(parsed, dict) and "message" in parsed:
                    return AdapterResponse.model_validate(parsed)
            except Exception:
                pass

        return AdapterResponse(
            events=events,
            message=AdapterMessage(kind=MessageKind.PROPOSAL, content=out_text or "Process completed with no output."),
        )

    def _kill_process_tree(self, pid: int) -> None:
        """Kill entire process tree to prevent orphaned child processes."""
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False)
            else:
                try:
                    import psutil

                    parent = psutil.Process(pid)
                    children = parent.children(recursive=True)
                    for child in children:
                        child.kill()
                    parent.kill()
                except ImportError:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
        except Exception:
            pass
