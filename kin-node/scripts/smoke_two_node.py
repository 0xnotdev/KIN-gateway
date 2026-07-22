#!/usr/bin/env python3
"""Two-process local smoke test harness for KIN (proves M0 over real sockets)."""

from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import httpx


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def read_until(p: subprocess.Popen[bytes], target: str, timeout: float = 15.0) -> str:
    buf = ""
    start = time.time()
    while target not in buf:
        if time.time() - start > timeout:
            p.kill()
            out, err = p.communicate()
            raise RuntimeError(
                f"Timeout waiting for '{target}' in output.\nCaptured so far:\n{buf}\n"
                f"STDOUT:\n{out.decode('utf-8', errors='replace')}\n"
                f"STDERR:\n{err.decode('utf-8', errors='replace')}"
            )
        try:
            chunk = os.read(p.stdout.fileno(), 1024).decode("utf-8", errors="replace")
            if not chunk and p.poll() is not None:
                break
            buf += chunk
        except Exception:
            time.sleep(0.05)
    return buf


def write_input(p: subprocess.Popen[bytes], text: str) -> None:
    data = (text + "\n").encode("utf-8")
    os.write(p.stdin.fileno(), data)


def main() -> None:
    procs: list[tuple[str, subprocess.Popen]] = []
    failed = False
    temp_dir = pathlib.Path(tempfile.mkdtemp(prefix="kin_smoke_"))

    try:
        relay_port = find_free_port()
        alice_port = find_free_port()
        bob_port = find_free_port()

        print(f"SMOKE: Selected real ports -> relay: {relay_port}, alice: {alice_port}, bob: {bob_port}", file=sys.stderr)

        relay_dir = temp_dir / "relay"
        relay_dir.mkdir()
        alice_home = temp_dir / "alice_home"
        alice_home.mkdir()
        bob_home = temp_dir / "bob_home"
        bob_home.mkdir()

        repo_root_node = pathlib.Path(__file__).parent.parent.resolve()
        repo_root_relay = (repo_root_node.parent / "kin-relay").resolve()

        base_pythonpath = os.environ.get("PYTHONPATH", "")
        smoke_pythonpath = f"{repo_root_node}{os.pathsep}{repo_root_relay}"
        if base_pythonpath:
            smoke_pythonpath = f"{smoke_pythonpath}{os.pathsep}{base_pythonpath}"

        fake_llm_json = json.dumps({"reply": "4", "message_type": "answer"})

        relay_env = os.environ.copy()
        relay_env["PYTHONPATH"] = smoke_pythonpath

        alice_env = os.environ.copy()
        alice_env["HOME"] = str(alice_home)
        alice_env["USERPROFILE"] = str(alice_home)
        alice_env["KIN_RELAY_URL"] = f"http://127.0.0.1:{relay_port}"
        alice_env["KIN_UNSAFE_TEST_KEYRING"] = "1"
        alice_env["KIN_TEST_KEYRING_PATH"] = str(alice_home / "keyring.json")
        alice_env["KIN_FAKE_LLM_RESPONSE"] = fake_llm_json
        alice_env["PYTHONPATH"] = smoke_pythonpath

        bob_env = os.environ.copy()
        bob_env["HOME"] = str(bob_home)
        bob_env["USERPROFILE"] = str(bob_home)
        bob_env["KIN_RELAY_URL"] = f"http://127.0.0.1:{relay_port}"
        bob_env["KIN_UNSAFE_TEST_KEYRING"] = "1"
        bob_env["KIN_TEST_KEYRING_PATH"] = str(bob_home / "keyring.json")
        bob_env["KIN_FAKE_LLM_RESPONSE"] = fake_llm_json
        bob_env["PYTHONPATH"] = smoke_pythonpath

        # a. Start kin-relay on free port
        relay_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "kin_relay.app:app", "--host", "127.0.0.1", "--port", str(relay_port)],
            cwd=relay_dir,
            env=relay_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        procs.append(("kin-relay", relay_proc))

        # Poll relay health
        relay_ok = False
        for _ in range(30):
            try:
                r = httpx.get(f"http://127.0.0.1:{relay_port}/directory/lookup/nonexistent", timeout=1.0)
                if r.status_code == 404:
                    relay_ok = True
                    break
            except Exception:
                time.sleep(0.2)
        if not relay_ok:
            raise RuntimeError("kin-relay failed to start on real socket port")

        # b. Setup identity for Alice and Bob non-interactively
        def setup_identity(profile: str, username: str, env: dict[str, str]) -> None:
            cmd = [sys.executable, "-m", "kin.cli", "--profile", profile, "pair"]
            p = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )

            read_until(p, "Choose your desired username")
            write_input(p, username)

            out_buf = read_until(p, "Enter word #")
            phrase_words = []
            for line in out_buf.splitlines():
                words = line.strip().split()
                if len(words) == 12 and all(w.isalpha() for w in words):
                    phrase_words = words
                    break

            if len(phrase_words) != 12:
                match = re.search(r"\n(([a-z]+\s+){11}[a-z]+)\n", out_buf)
                if match:
                    phrase_words = match.group(1).split()

            if len(phrase_words) != 12:
                p.kill()
                out, err = p.communicate()
                raise RuntimeError(f"Failed to capture 12-word phrase for {profile}.\nOutput:\n{out_buf}\nSTDOUT:\n{out.decode()}\nSTDERR:\n{err.decode()}")

            m1 = re.search(r"Enter word #(\d+)", out_buf)
            if not m1:
                raise RuntimeError(f"Failed to parse word prompt #1 for {profile}. Output:\n{out_buf}")
            idx1 = int(m1.group(1)) - 1
            write_input(p, phrase_words[idx1])

            out_buf2 = read_until(p, "Enter word #")
            m2 = re.search(r"Enter word #(\d+)", out_buf2)
            if not m2:
                raise RuntimeError(f"Failed to parse word prompt #2 for {profile}. Output:\n{out_buf2}")
            idx2 = int(m2.group(1)) - 1
            write_input(p, phrase_words[idx2])

            stdout, stderr = p.communicate(timeout=10)
            if p.returncode != 0:
                raise RuntimeError(f"Identity setup failed for {profile} (code {p.returncode}):\n{stdout.decode()}\n{stderr.decode()}")

        setup_identity("alice", "alice", alice_env)
        setup_identity("bob", "bob", bob_env)

        # e. Start Alice and Bob node servers on real ports
        alice_node_proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "kin.cli",
                "--profile",
                "alice",
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(alice_port),
                "--public-endpoint",
                f"http://127.0.0.1:{alice_port}",
                "--no-fetch",
            ],
            env=alice_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        procs.append(("alice-node", alice_node_proc))

        bob_node_proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "kin.cli",
                "--profile",
                "bob",
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(bob_port),
                "--public-endpoint",
                f"http://127.0.0.1:{bob_port}",
                "--no-fetch",
            ],
            env=bob_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        procs.append(("bob-node", bob_node_proc))

        def poll_agent_card(port: int, name: str) -> None:
            ok = False
            url = f"http://127.0.0.1:{port}/.well-known/agent-card.json"
            for _ in range(30):
                try:
                    r = httpx.get(url, timeout=1.0)
                    if r.status_code == 200:
                        ok = True
                        break
                except Exception:
                    time.sleep(0.2)
            if not ok:
                raise RuntimeError(f"{name} node server failed to respond on port {port}")

        poll_agent_card(alice_port, "alice")
        poll_agent_card(bob_port, "bob")

        # f. Run kin pair between alice and bob in both directions and compare fingerprints
        p_alice_pair = subprocess.Popen(
            [sys.executable, "-m", "kin.cli", "--profile", "alice", "pair", "bob"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=alice_env,
        )

        out_a = read_until(p_alice_pair, "Does it match?")
        fp_a_match = re.search(r"Computed Fingerprint:\s*([^\s=]+)", out_a)
        if not fp_a_match:
            raise RuntimeError(f"Alice failed to compute fingerprint for Bob:\n{out_a}")
        fp_alice = fp_a_match.group(1)

        p_bob_pair = subprocess.Popen(
            [sys.executable, "-m", "kin.cli", "--profile", "bob", "pair", "alice"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=bob_env,
        )

        out_b = read_until(p_bob_pair, "Does it match?")
        fp_b_match = re.search(r"Computed Fingerprint:\s*([^\s=]+)", out_b)
        if not fp_b_match:
            raise RuntimeError(f"Bob failed to compute fingerprint for Alice:\n{out_b}")
        fp_bob = fp_b_match.group(1)

        if fp_alice != fp_bob:
            raise RuntimeError(f"Fingerprint mismatch! Alice: {fp_alice}, Bob: {fp_bob}")

        print(f"SMOKE: Computed Fingerprints MATCH -> alice: {fp_alice}, bob: {fp_bob}", file=sys.stderr)

        write_input(p_alice_pair, "y")
        out_a_rem, err_a = p_alice_pair.communicate(timeout=5)
        if p_alice_pair.returncode != 0:
            raise RuntimeError(f"Alice pair failed: {out_a_rem.decode()}\n{err_a.decode()}")

        write_input(p_bob_pair, "y")
        out_b_rem, err_b = p_bob_pair.communicate(timeout=5)
        if p_bob_pair.returncode != 0:
            raise RuntimeError(f"Bob pair failed: {out_b_rem.decode()}\n{err_b.decode()}")

        # h. Run kin ask
        ask_res = subprocess.run(
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
            env=alice_env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if ask_res.returncode != 0:
            raise RuntimeError(f"kin ask failed:\nSTDOUT:\n{ask_res.stdout}\nSTDERR:\n{ask_res.stderr}")

        task_id_match = re.search(r"ID:\s*([a-zA-Z0-9_-]+)", ask_res.stdout)
        if not task_id_match:
            raise RuntimeError(f"Failed to parse task_id from ask output:\n{ask_res.stdout}")
        task_id = task_id_match.group(1)

        print(f"SMOKE: Created task_id -> {task_id}", file=sys.stderr)

        # i. Poll bob's tasks
        task_found = False
        bob_tasks_stdout = ""
        bob_tasks_stderr = ""
        for _ in range(20):
            res_tasks = subprocess.run(
                [sys.executable, "-m", "kin.cli", "--profile", "bob", "tasks", "--status", "input-required"],
                env=bob_env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            bob_tasks_stdout = res_tasks.stdout
            bob_tasks_stderr = res_tasks.stderr
            if task_id in res_tasks.stdout:
                task_found = True
                break
            time.sleep(0.5)

        if not task_found:
            raise RuntimeError(
                f"Timed out waiting for task {task_id} in bob's tasks --status input-required.\n"
                f"STDOUT:\n{bob_tasks_stdout}\nSTDERR:\n{bob_tasks_stderr}"
            )

        print(f"SMOKE: Bob's drafted tasks content:\n{bob_tasks_stdout.strip()}", file=sys.stderr)

        # j. Run respond on bob's side, feeding "f" (finalize proposal)
        p_respond_bob = subprocess.Popen(
            [sys.executable, "-m", "kin.cli", "--profile", "bob", "respond", task_id],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=bob_env,
        )
        resp_stdout, resp_stderr = p_respond_bob.communicate(input=b"f\n", timeout=10)
        if p_respond_bob.returncode != 0:
            p_respond_bob2 = subprocess.Popen(
                [sys.executable, "-m", "kin.cli", "--profile", "bob", "respond", task_id],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=bob_env,
            )
            resp_stdout, resp_stderr = p_respond_bob2.communicate(input=b"y\n", timeout=10)

        # Poll alice status: if input-required (proposal received), respond with "a" (accept)
        status_completed = False
        alice_status_stdout = ""
        alice_status_stderr = ""
        for _ in range(20):
            res_status = subprocess.run(
                [sys.executable, "-m", "kin.cli", "--profile", "alice", "status", task_id],
                env=alice_env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            alice_status_stdout = res_status.stdout
            alice_status_stderr = res_status.stderr
            if "completed" in res_status.stdout.lower():
                status_completed = True
                break
            elif "input-required" in res_status.stdout.lower():
                p_respond_alice = subprocess.Popen(
                    [sys.executable, "-m", "kin.cli", "--profile", "alice", "respond", task_id],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=alice_env,
                )
                p_respond_alice.communicate(input=b"a\n", timeout=10)
            time.sleep(0.5)

        if not status_completed:
            raise RuntimeError(
                f"Timed out waiting for task {task_id} status=completed.\n"
                f"STDOUT:\n{alice_status_stdout}\nSTDERR:\n{alice_status_stderr}"
            )

        # l. Assert transcript contains "4"
        if "4" not in alice_status_stdout:
            raise RuntimeError(f"Alice status transcript did not contain expected answer '4'. Output:\n{alice_status_stdout}")

        print(f"SMOKE: Full Alice transcript at completion:\n{alice_status_stdout.strip()}", file=sys.stderr)

        print("PASS: Two-process local smoke test over real sockets succeeded!")

    except Exception as e:
        failed = True
        print(f"FAIL: Two-process local smoke test failed: {e}", file=sys.stderr)
        raise
    finally:
        for name, proc in procs:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()

        # Clean up temp directory and key material
        shutil.rmtree(temp_dir, ignore_errors=True)

        if failed:
            print("\n=== SUBPROCESS OUTPUT CAPTURE ON FAILURE ===", file=sys.stderr)
            for name, proc in procs:
                out, err = proc.communicate()
                print(f"\n--- Process: {name} ---", file=sys.stderr)
                print(f"STDOUT:\n{out.decode('utf-8', errors='replace')}", file=sys.stderr)
                print(f"STDERR:\n{err.decode('utf-8', errors='replace')}", file=sys.stderr)


if __name__ == "__main__":
    main()
