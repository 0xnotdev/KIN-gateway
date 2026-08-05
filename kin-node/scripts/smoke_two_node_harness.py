#!/usr/bin/env python3
"""Shared real relay + two-node process harness for KIN smoke tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any

import httpx


def find_free_port(excluded: set[int] | None = None) -> int:
    excluded = excluded or set()
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = int(sock.getsockname()[1])
        if port not in excluded:
            return port


def read_until(process: subprocess.Popen[bytes], target: str, timeout: float = 15.0) -> str:
    buffer = ""
    started = time.monotonic()
    while target not in buffer:
        if time.monotonic() - started > timeout:
            process.kill()
            stdout, stderr = process.communicate()
            raise RuntimeError(
                f"Timeout waiting for '{target}'.\nCaptured:\n{buffer}\n"
                f"STDOUT:\n{stdout.decode('utf-8', errors='replace')}\n"
                f"STDERR:\n{stderr.decode('utf-8', errors='replace')}"
            )
        chunk = os.read(process.stdout.fileno(), 1024).decode("utf-8", errors="replace")
        if not chunk and process.poll() is not None:
            break
        buffer += chunk
    return buffer


def write_input(process: subprocess.Popen[bytes], value: str) -> None:
    os.write(process.stdin.fileno(), (value + "\n").encode("utf-8"))


class TwoNodeSmokeHarness:
    """Own one relay and two isolated real KIN node subprocesses."""

    def __init__(self, *, enable_v11: bool = True) -> None:
        self.processes: list[tuple[str, subprocess.Popen[bytes]]] = []
        self.temp_dir = Path(tempfile.mkdtemp(prefix="kin_smoke_"))
        ports: set[int] = set()
        self.relay_port = find_free_port(ports)
        ports.add(self.relay_port)
        self.alice_port = find_free_port(ports)
        ports.add(self.alice_port)
        self.bob_port = find_free_port(ports)

        self.relay_dir = self.temp_dir / "relay"
        self.alice_home = self.temp_dir / "alice_home"
        self.bob_home = self.temp_dir / "bob_home"
        for directory in (self.relay_dir, self.alice_home, self.bob_home):
            directory.mkdir(parents=True)

        self.repo_root = Path(__file__).parent.parent.resolve()
        self.relay_root = (self.repo_root.parent / "kin-relay").resolve()
        python_path = os.pathsep.join((str(self.repo_root), str(self.relay_root)))
        if os.environ.get("PYTHONPATH"):
            python_path += os.pathsep + os.environ["PYTHONPATH"]

        self.relay_env = os.environ.copy()
        self.relay_env["PYTHONPATH"] = python_path
        self.alice_env = self._profile_environment(self.alice_home, python_path)
        self.bob_env = self._profile_environment(self.bob_home, python_path)
        self.started = False
        self.enable_v11 = enable_v11
        self.node_processes: dict[str, subprocess.Popen[bytes]] = {}

    @property
    def alice_profile_dir(self) -> Path:
        return self.alice_home / ".kin" / "profiles" / "alice"

    @property
    def bob_profile_dir(self) -> Path:
        return self.bob_home / ".kin" / "profiles" / "bob"

    def _profile_environment(self, home: Path, python_path: str) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(
            {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "KIN_RELAY_URL": f"http://127.0.0.1:{self.relay_port}",
                "KIN_UNSAFE_TEST_KEYRING": "1",
                "KIN_TEST_KEYRING_PATH": str(home / "keyring.json"),
                "KIN_FAKE_LLM_RESPONSE": json.dumps({"reply": "4", "message_type": "answer"}),
                "PYTHONPATH": python_path,
            }
        )
        return environment

    def start(self) -> "TwoNodeSmokeHarness":
        if self.started:
            return self
        print(
            "SMOKE: Selected real ports -> "
            f"relay: {self.relay_port}, alice: {self.alice_port}, bob: {self.bob_port}",
            file=sys.stderr,
        )
        self._start_relay()
        self._setup_identity("alice", self.alice_env)
        self._setup_identity("bob", self.bob_env)
        if self.enable_v11:
            self._import_agent("alice", "alice_agent", self.alice_env)
            self._import_agent("bob", "bob_agent", self.bob_env)
        self._start_node("alice", self.alice_port, self.alice_env)
        self._start_node("bob", self.bob_port, self.bob_env)
        self._pair_profiles()
        if self.enable_v11:
            alice_cards = self.run_worker("alice", "sync-cards", "--peer", "bob")
            bob_cards = self.run_worker("bob", "sync-cards", "--peer", "alice")
            if alice_cards.get("source") != "network" or alice_cards.get("card_count") != 1:
                raise RuntimeError(f"Alice failed to sync Bob's real card: {alice_cards}")
            if bob_cards.get("source") != "network" or bob_cards.get("card_count") != 1:
                raise RuntimeError(f"Bob failed to sync Alice's real card: {bob_cards}")
            alice_capabilities = self.run_worker("alice", "sync-capabilities", "--peer", "bob")
            bob_capabilities = self.run_worker("bob", "sync-capabilities", "--peer", "alice")
            if alice_capabilities.get("source") != "network":
                raise RuntimeError(f"Alice failed to cache Bob's real capabilities: {alice_capabilities}")
            if bob_capabilities.get("source") != "network":
                raise RuntimeError(f"Bob failed to cache Alice's real capabilities: {bob_capabilities}")
        self.started = True
        return self

    def _start_relay(self) -> None:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "kin_relay.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.relay_port),
            ],
            cwd=self.relay_dir,
            env=self.relay_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.processes.append(("kin-relay", process))
        for _ in range(40):
            try:
                response = httpx.get(
                    f"http://127.0.0.1:{self.relay_port}/directory/lookup/nonexistent",
                    timeout=1.0,
                )
                if response.status_code == 404:
                    return
            except httpx.HTTPError:
                time.sleep(0.2)
        raise RuntimeError("kin-relay failed to start on its real socket")

    def _setup_identity(self, profile: str, environment: dict[str, str]) -> None:
        process = subprocess.Popen(
            [sys.executable, "-m", "kin.cli", "--profile", profile, "pair"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )
        first_output = read_until(process, "Choose your desired username")
        write_input(process, profile)
        phrase_output = read_until(process, "Enter word #")
        phrase_words: list[str] = []
        for line in phrase_output.splitlines():
            words = line.strip().split()
            if len(words) == 12 and all(word.isalpha() for word in words):
                phrase_words = words
                break
        if not phrase_words:
            match = re.search(r"\n(([a-z]+\s+){11}[a-z]+)\n", phrase_output)
            if match:
                phrase_words = match.group(1).split()
        if len(phrase_words) != 12:
            raise RuntimeError(
                f"Failed to capture recovery phrase for {profile}.\n"
                f"Initial output:\n{first_output}\nPhrase output:\n{phrase_output}"
            )
        first_prompt = re.search(r"Enter word #(\d+)", phrase_output)
        if not first_prompt:
            raise RuntimeError(f"Failed to parse first recovery prompt for {profile}")
        write_input(process, phrase_words[int(first_prompt.group(1)) - 1])
        second_output = read_until(process, "Enter word #")
        second_prompt = re.search(r"Enter word #(\d+)", second_output)
        if not second_prompt:
            raise RuntimeError(f"Failed to parse second recovery prompt for {profile}")
        write_input(process, phrase_words[int(second_prompt.group(1)) - 1])
        stdout, stderr = process.communicate(timeout=15)
        if process.returncode != 0:
            raise RuntimeError(
                f"Identity setup failed for {profile}.\n"
                f"STDOUT:\n{stdout.decode(errors='replace')}\n"
                f"STDERR:\n{stderr.decode(errors='replace')}"
            )

    def _import_agent(self, profile: str, agent_id: str, environment: dict[str, str]) -> None:
        card_path = self.temp_dir / f"{agent_id}.yaml"
        card_path.write_text(
            "\n".join(
                (
                    'schema_version: "1.1"',
                    f"id: {agent_id}",
                    f"name: {profile.title()} Smoke Agent",
                    "description: Deterministic real-node smoke agent",
                    "adapter:",
                    "  type: embedded",
                    "  provider: smoke",
                    "  model: deterministic",
                    "capabilities:",
                    "  tags: [smoke]",
                    "  accepts: [text/plain]",
                    "  produces: [text/plain]",
                    "boundaries:",
                    "  network_access: deny",
                    "  filesystem: none",
                    "  shell: deny",
                    "  max_runtime_seconds: 60",
                    "  max_artifact_bytes: 1000000",
                    "autonomy:",
                    "  relay_information: always_ask",
                    "  propose_actions: always_ask",
                    "  execute_local_actions: always_ask",
                    "",
                )
            ),
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, "-m", "kin.cli", "--profile", profile, "agent", "import", str(card_path)],
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Agent import failed for {profile}.\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )

    def _start_node(self, profile: str, port: int, environment: dict[str, str]) -> None:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "kin.cli",
                "--profile",
                profile,
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--public-endpoint",
                f"http://127.0.0.1:{port}",
                "--no-fetch",
            ],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.processes.append((f"{profile}-node", process))
        self.node_processes[profile] = process
        for _ in range(40):
            try:
                response = httpx.get(
                    f"http://127.0.0.1:{port}/.well-known/agent-card.json", timeout=1.0
                )
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.2)
        raise RuntimeError(f"{profile} node failed to start on its real socket")

    def stop_node(self, profile: str, *, crash: bool = True) -> int:
        """Stop a real node, using SIGTERM for the Phase B crash simulation."""
        process = self.node_processes.get(profile)
        if process is None:
            raise RuntimeError(f"No {profile} node process has been started")
        if process.poll() is None:
            if crash:
                process.send_signal(signal.SIGTERM)
            else:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        print(
            f"SMOKE: {profile} node stopped via {'SIGTERM' if crash else 'terminate'} "
            f"with returncode={process.returncode}",
            file=sys.stderr,
        )
        return int(process.returncode or 0)

    def restart_node(self, profile: str) -> subprocess.Popen[bytes]:
        """Restart a node on its original port against its unchanged profile directory."""
        if profile == "alice":
            port, environment = self.alice_port, self.alice_env
        elif profile == "bob":
            port, environment = self.bob_port, self.bob_env
        else:
            raise ValueError(f"Unknown profile: {profile}")
        self._start_node(profile, port, environment)
        print(
            f"SMOKE: {profile} node restarted on port={port} with profile_dir="
            f"{self.alice_profile_dir if profile == 'alice' else self.bob_profile_dir}",
            file=sys.stderr,
        )
        return self.node_processes[profile]

    def _pair_profiles(self) -> None:
        alice_pair = self._start_pair("alice", "bob", self.alice_env)
        alice_output = read_until(alice_pair, "Does it match?")
        bob_pair = self._start_pair("bob", "alice", self.bob_env)
        bob_output = read_until(bob_pair, "Does it match?")
        alice_match = re.search(r"Computed Fingerprint:\s*([^\s=]+)", alice_output)
        bob_match = re.search(r"Computed Fingerprint:\s*([^\s=]+)", bob_output)
        if not alice_match or not bob_match or alice_match.group(1) != bob_match.group(1):
            raise RuntimeError(
                f"Pair fingerprint mismatch.\nAlice:\n{alice_output}\nBob:\n{bob_output}"
            )
        print(
            "SMOKE: Computed Fingerprints MATCH -> "
            f"alice: {alice_match.group(1)}, bob: {bob_match.group(1)}",
            file=sys.stderr,
        )
        for profile, process in (("alice", alice_pair), ("bob", bob_pair)):
            write_input(process, "y")
            stdout, stderr = process.communicate(timeout=10)
            if process.returncode != 0:
                raise RuntimeError(
                    f"{profile} pair confirmation failed.\n"
                    f"STDOUT:\n{stdout.decode(errors='replace')}\n"
                    f"STDERR:\n{stderr.decode(errors='replace')}"
                )

    @staticmethod
    def _start_pair(
        profile: str, peer: str, environment: dict[str, str]
    ) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            [sys.executable, "-m", "kin.cli", "--profile", profile, "pair", peer],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
        )

    def run_worker(self, profile: str, operation: str, *arguments: str) -> dict[str, Any]:
        environment = self.alice_env if profile == "alice" else self.bob_env
        result = subprocess.run(
            [
                sys.executable,
                str(self.repo_root / "scripts" / "smoke_v11_worker.py"),
                "--profile",
                profile,
                operation,
                *arguments,
            ],
            env=environment,
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"{profile} worker '{operation}' failed.\n"
                f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            raise RuntimeError(f"{profile} worker '{operation}' emitted no JSON")
        return json.loads(lines[-1])

    def run_v11_lifecycle(self, goal: str = "Coordinate a real V1.1 smoke collaboration") -> dict[str, Any]:
        dispatch = self.run_worker(
            "alice",
            "dispatch",
            "--peer",
            "bob",
            "--sender-agent",
            "alice_agent",
            "--receiver-agent",
            "bob_agent",
            "--goal",
            goal,
        )
        if dispatch.get("status") != "delivered":
            raise RuntimeError(f"V1.1 dispatch was not delivered directly: {dispatch}")
        session_id = str(dispatch["session_id"])
        bob_received = self.run_worker("bob", "inspect", "--session", session_id)
        if not bob_received.get("found") or bob_received.get("status") not in {
            "delivered",
            "peer_review",
        }:
            raise RuntimeError(f"Bob did not persist the delivered session: {bob_received}")
        if bob_received.get("goal") != goal or bob_received.get("event_count") != 1:
            raise RuntimeError(f"Bob's persisted request does not match dispatch: {bob_received}")

        self.run_worker(
            "bob",
            "respond",
            "--session",
            session_id,
            "--decision",
            "accept",
            "--agent",
            "bob_agent",
            "--text",
            "Accepted over the real node boundary",
        )
        self.run_worker(
            "alice",
            "message",
            "--session",
            session_id,
            "--kind",
            "question",
            "--actor-agent",
            "alice_agent",
            "--text",
            "What evidence did the real peer receive?",
        )
        self.run_worker(
            "bob",
            "message",
            "--session",
            session_id,
            "--kind",
            "answer",
            "--actor-agent",
            "bob_agent",
            "--text",
            "The signed V1.1 task request and question.",
        )
        self.run_worker(
            "bob",
            "message",
            "--session",
            session_id,
            "--kind",
            "final_result",
            "--actor-agent",
            "bob_agent",
            "--text",
            "Real-network collaboration completed.",
        )
        alice_final = self.run_worker("alice", "inspect", "--session", session_id)
        bob_final = self.run_worker("bob", "inspect", "--session", session_id)
        for profile, evidence in (("Alice", alice_final), ("Bob", bob_final)):
            expected_kinds = [
                "task_request", "acceptance", "question", "answer", "final_result", "outcome"
            ]
            if (
                evidence.get("status") != "completed"
                or evidence.get("event_count") != 6
                or evidence.get("event_kinds") != expected_kinds
            ):
                raise RuntimeError(f"{profile} did not reach the complete persisted outcome state: {evidence}")
        return {
            "session_id": session_id,
            "dispatch": dispatch,
            "bob_received": bob_received,
            "alice_final": alice_final,
            "bob_final": bob_final,
        }

    def run_v11_phase_b(self) -> dict[str, Any]:
        """Exercise Phase B relay, restart, expiry, and artifact persistence gates."""
        # 1. Bob is offline at dispatch; the real relay retains exactly one envelope.
        self.stop_node("bob", crash=True)
        relay_dispatch = self.run_worker(
            "alice",
            "dispatch",
            "--peer",
            "bob",
            "--sender-agent",
            "alice_agent",
            "--receiver-agent",
            "bob_agent",
            "--goal",
            "Queue this V1.1 session while Bob is offline",
        )
        if relay_dispatch.get("status") != "queued":
            raise RuntimeError(f"Offline dispatch did not queue at real relay: {relay_dispatch}")
        relay_session_id = str(relay_dispatch["session_id"])
        queued_mailbox = self.run_worker("bob", "relay-inbox")
        if queued_mailbox.get("message_count") != 1 or queued_mailbox.get("senders") != ["alice"]:
            raise RuntimeError(f"Real relay mailbox did not retain Alice's envelope: {queued_mailbox}")

        self.restart_node("bob")
        first_poll = self.run_worker("bob", "poll-relay")
        bob_relay_received = self.run_worker("bob", "inspect", "--session", relay_session_id)
        empty_mailbox = self.run_worker("bob", "relay-inbox")
        second_poll = self.run_worker("bob", "poll-relay")
        bob_after_second_poll = self.run_worker("bob", "inspect", "--session", relay_session_id)
        if not bob_relay_received.get("found") or bob_relay_received.get("event_count") != 1:
            raise RuntimeError(f"Bob did not persist relay-delivered session: {bob_relay_received}")
        first_poll_count = first_poll.get("processed_count")
        if first_poll_count not in (0, 1):
            raise RuntimeError(f"Bob's relay synchronization returned an invalid count: {first_poll}")
        relay_consumer = "production-background-loop" if first_poll_count == 0 else "explicit-worker-poll"
        if empty_mailbox.get("message_count") != 0 or second_poll.get("processed_count") != 0:
            raise RuntimeError(
                f"Relay ACK/idempotency failed: mailbox={empty_mailbox}, second_poll={second_poll}"
            )
        if bob_after_second_poll.get("event_count") != 1:
            raise RuntimeError(f"Second fetch duplicated Bob's event: {bob_after_second_poll}")

        # 2. Crash/restart Alice mid-session and reconstruct exclusively from persisted state.
        restart_dispatch = self.run_worker(
            "alice",
            "dispatch",
            "--peer",
            "bob",
            "--sender-agent",
            "alice_agent",
            "--receiver-agent",
            "bob_agent",
            "--goal",
            "Reconstruct this active session after Alice crashes",
        )
        restart_session_id = str(restart_dispatch["session_id"])
        self.run_worker(
            "bob", "respond", "--session", restart_session_id,
            "--decision", "accept", "--agent", "bob_agent", "--text", "Accepted before crash",
        )
        self.run_worker(
            "alice", "message", "--session", restart_session_id, "--kind", "question",
            "--actor-agent", "alice_agent", "--text", "Will this survive SIGTERM?",
        )
        self.run_worker(
            "bob", "message", "--session", restart_session_id, "--kind", "answer",
            "--actor-agent", "bob_agent", "--text", "The SQLite audit trail will survive.",
        )
        before_crash = self.run_worker("alice", "inspect", "--session", restart_session_id)
        if before_crash.get("status") != "active" or before_crash.get("event_count") != 4:
            raise RuntimeError(f"Restart scenario was not active at crash point: {before_crash}")
        crash_returncode = self.stop_node("alice", crash=True)
        self.restart_node("alice")
        reconstructed = self.run_worker("alice", "reconstruct", "--session", restart_session_id)
        if reconstructed.get("status") != "active" or reconstructed.get("event_count") != 4:
            raise RuntimeError(f"Alice failed to reconstruct active state after SIGTERM: {reconstructed}")
        self.run_worker(
            "bob", "message", "--session", restart_session_id, "--kind", "final_result",
            "--actor-agent", "bob_agent", "--text", "Restart reconstruction completed.",
        )
        restart_final = self.run_worker("alice", "inspect", "--session", restart_session_id)
        if restart_final.get("status") != "completed" or restart_final.get("event_count") != 6:
            raise RuntimeError(f"Restarted Alice missed or duplicated terminal event: {restart_final}")

        # 3. A genuinely elapsed, test-shortened approval is rejected by the real TUI command.
        expiry_dispatch = self.run_worker(
            "alice", "dispatch", "--peer", "bob", "--sender-agent", "alice_agent",
            "--receiver-agent", "bob_agent", "--goal", "Expire a real pending approval",
        )
        expiry_session_id = str(expiry_dispatch["session_id"])
        self.run_worker(
            "bob", "respond", "--session", expiry_session_id, "--decision", "accept",
            "--agent", "bob_agent", "--text", "Accepted for expiry proof",
        )
        approval = self.run_worker(
            "alice", "create-expiring-approval", "--session", expiry_session_id,
            "--agent", "alice_agent", "--expiry-seconds", "0.5",
        )
        time.sleep(0.8)
        expiry_decision = self.run_worker(
            "alice", "decide-approval", "--session", expiry_session_id,
            "--approval", str(approval["approval_id"]), "--decision", "approve_once",
        )
        if expiry_decision.get("success") is not False:
            raise RuntimeError(f"Expired approval decision unexpectedly succeeded: {expiry_decision}")
        if "has expired" not in str(expiry_decision.get("error")) or expiry_decision.get("decision") is not None:
            raise RuntimeError(f"Expired approval did not return the specific preserved-state error: {expiry_decision}")

        # 4. A peer-received artifact remains decryptable with its provenance after Bob restarts.
        artifact_dispatch = self.run_worker(
            "alice", "dispatch", "--peer", "bob", "--sender-agent", "alice_agent",
            "--receiver-agent", "bob_agent", "--goal", "Persist artifact metadata across Bob restart",
        )
        artifact_session_id = str(artifact_dispatch["session_id"])
        self.run_worker(
            "bob", "respond", "--session", artifact_session_id, "--decision", "accept",
            "--agent", "bob_agent", "--text", "Accepted for artifact proof",
        )
        artifact_text = "Phase B restart-persistent artifact payload"
        artifact_offer = self.run_worker(
            "alice", "artifact-offer", "--session", artifact_session_id, "--text", artifact_text,
        )
        if artifact_offer.get("delivery") != "direct":
            raise RuntimeError(f"Artifact was not offered over the real Bob node: {artifact_offer}")
        artifact_id = str(artifact_offer["artifact_id"])
        artifact_before = self.run_worker("bob", "inspect-artifact", "--artifact", artifact_id)
        self.stop_node("bob", crash=True)
        self.restart_node("bob")
        artifact_after = self.run_worker("bob", "inspect-artifact", "--artifact", artifact_id)
        if artifact_before != artifact_after:
            raise RuntimeError(
                f"Artifact metadata/content changed across Bob restart: before={artifact_before}, after={artifact_after}"
            )
        if (
            artifact_after.get("sha256") != artifact_after.get("computed_sha256")
            or artifact_after.get("sha256") != artifact_offer.get("sha256")
            or artifact_after.get("offered_by") != "alice"
            or artifact_after.get("source") != "peer_received"
            or artifact_after.get("content") != artifact_text
        ):
            raise RuntimeError(f"Restarted artifact proof failed hash/provenance checks: {artifact_after}")

        return {
            "relay": {
                "session_id": relay_session_id,
                "dispatch": relay_dispatch,
                "queued_mailbox": queued_mailbox,
                "first_poll": first_poll,
                "relay_consumer": relay_consumer,
                "empty_mailbox": empty_mailbox,
                "second_poll": second_poll,
                "bob_after_second_poll": bob_after_second_poll,
            },
            "restart": {
                "session_id": restart_session_id,
                "sigterm_returncode": crash_returncode,
                "before_crash": before_crash,
                "reconstructed": reconstructed,
                "final": restart_final,
            },
            "expiry": {
                "session_id": expiry_session_id,
                "approval": approval,
                "decision": expiry_decision,
            },
            "artifact": {
                "session_id": artifact_session_id,
                "offer": artifact_offer,
                "before_restart": artifact_before,
                "after_restart": artifact_after,
            },
        }

    def run_legacy_task_lifecycle(self) -> dict[str, Any]:
        """Preserve the original M0 ask/respond real-socket proof on this setup."""
        ask_result = subprocess.run(
            [
                sys.executable,
                "-m",
                "kin.cli",
                "--profile",
                "alice",
                "ask",
                "bob",
                "What is 2+2? Reply with just the number.",
            ],
            env=self.alice_env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if ask_result.returncode != 0:
            raise RuntimeError(
                f"kin ask failed.\nSTDOUT:\n{ask_result.stdout}\nSTDERR:\n{ask_result.stderr}"
            )
        task_match = re.search(r"ID:\s*([a-zA-Z0-9_-]+)", ask_result.stdout)
        if not task_match:
            raise RuntimeError(f"Failed to parse task ID from ask output:\n{ask_result.stdout}")
        task_id = task_match.group(1)

        bob_tasks_output = ""
        for _ in range(30):
            tasks_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "kin.cli",
                    "--profile",
                    "bob",
                    "tasks",
                    "--status",
                    "input-required",
                ],
                env=self.bob_env,
                capture_output=True,
                text=True,
                timeout=15,
            )
            bob_tasks_output = tasks_result.stdout
            if task_id in bob_tasks_output:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError(f"Bob did not receive legacy task {task_id}:\n{bob_tasks_output}")

        response = subprocess.run(
            [sys.executable, "-m", "kin.cli", "--profile", "bob", "respond", task_id],
            env=self.bob_env,
            input="f\n",
            capture_output=True,
            text=True,
            timeout=20,
        )
        if response.returncode != 0:
            raise RuntimeError(
                f"Bob legacy response failed.\nSTDOUT:\n{response.stdout}\nSTDERR:\n{response.stderr}"
            )

        alice_status_output = ""
        for _ in range(30):
            status_result = subprocess.run(
                [sys.executable, "-m", "kin.cli", "--profile", "alice", "status", task_id],
                env=self.alice_env,
                capture_output=True,
                text=True,
                timeout=15,
            )
            alice_status_output = status_result.stdout
            if "completed" in alice_status_output.lower():
                break
            if "input-required" in alice_status_output.lower():
                subprocess.run(
                    [sys.executable, "-m", "kin.cli", "--profile", "alice", "respond", task_id],
                    env=self.alice_env,
                    input="a\n",
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            time.sleep(0.5)
        else:
            raise RuntimeError(
                f"Alice legacy task {task_id} did not complete:\n{alice_status_output}"
            )
        if "4" not in alice_status_output:
            raise RuntimeError(f"Legacy task transcript omitted answer 4:\n{alice_status_output}")
        return {
            "task_id": task_id,
            "bob_tasks": bob_tasks_output.strip(),
            "alice_transcript": alice_status_output.strip(),
        }

    def cleanup(self) -> None:
        for _, process in self.processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def failure_output(self) -> str:
        sections: list[str] = []
        for name, process in self.processes:
            if process.poll() is None:
                continue
            stdout, stderr = process.communicate()
            sections.append(
                f"--- Process: {name} ---\n"
                f"STDOUT:\n{stdout.decode('utf-8', errors='replace')}\n"
                f"STDERR:\n{stderr.decode('utf-8', errors='replace')}"
            )
        return "\n\n".join(sections)

    def __enter__(self) -> "TwoNodeSmokeHarness":
        return self.start()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.cleanup()
