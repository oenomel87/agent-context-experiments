"""Pinned Codex SDK adapter for externally orchestrated synthetic roles.

Production use verifies OS-enforced file denial and effective restrictive permission
metadata. Residual tool exposure is disclosed; actual tool calls fail closed.
No monetary budget cap is asserted by this adapter.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import signal
import tempfile
import time
from pathlib import Path
from typing import Any

from codex_cli_bin import bundled_codex_path

MODEL = "gpt-6-luna"
PINNED_VERSION = "0.159.3"


class SDKIsolationError(RuntimeError):
    """The required zero-tool / clean-context execution profile is not verified."""


class SDKExecutionError(RuntimeError):
    """A session failed while preserving a reviewable result record."""
    def __init__(self, message: str, record: dict):
        super().__init__(message)
        self.record = record


def _dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def cumulative_usage_delta(current: dict | None, previous: dict | None) -> dict | None:
    if current is None:
        return None
    difference = {}
    for key, value in current.items():
        if not isinstance(value, int):
            difference[key] = None
        elif previous is None:
            difference[key] = value
        elif not isinstance(previous.get(key), int):
            difference[key] = None
        elif value < previous[key]:
            raise SDKIsolationError("Thread token usage counter decreased unexpectedly")
        else:
            difference[key] = value - previous[key]
    return difference


class SDKAdapter:
    """Async bridge to official TypeScript SDK; fresh role threads, persisted local history.

    Permission proof replaces the unattainable zero-tool-inventory gate. Residual
    tool exposure remains a disclosed limitation and actual invocations fail closed.
    """
    def __init__(self, *, development_probe: bool = False, **_unused):
        self.development_probe = development_probe
        self.process = None
        self.work_root = None
        self._active = asyncio.Lock()
        self.permission_evidence = None

    async def __aenter__(self):
        root = Path(__file__).resolve().parents[1]
        package_file = root / "node_modules/@openai/codex-sdk/package.json"
        if not package_file.exists() or json.loads(package_file.read_text())["version"] != PINNED_VERSION:
            raise SDKIsolationError("Pinned TypeScript SDK is missing or version differs")
        self.work_root = Path(tempfile.mkdtemp(prefix="luna-permission-check-", dir="/private/tmp"))
        root = Path(__file__).resolve().parents[1]
        cli = bundled_codex_path()
        canary = self.work_root.parent / (self.work_root.name + "-canary.txt")
        canary.write_text("SYNTHETIC-NONSECRET-CANARY")
        fs_profile = {":root": "deny", ":minimal": "read", ":workspace_roots": {".": "read"},
                      ":tmpdir": "deny", ":slash_tmp": "deny", str(Path.home()): "deny"}
        def toml_table(d):
            return "{" + ",".join(json.dumps(k) + "=" + (toml_table(v) if isinstance(v, dict) else json.dumps(v)) for k,v in d.items()) + "}"
        try:
            checker = await asyncio.create_subprocess_exec(str(cli), "sandbox", "--include-managed-config",
                "--permission-profile", "luna-locked", "--cd", str(self.work_root),
                "--config", "permissions.luna-locked.filesystem=" + toml_table(fs_profile),
                "--config", "permissions.luna-locked.network.enabled=false", "/bin/cat", str(canary),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, err = await asyncio.wait_for(checker.communicate(), 20)
            denied = checker.returncode != 0 and b"Operation not permitted" in err and b"SYNTHETIC" not in out
            self.permission_evidence = {"permission_profile": "luna-locked", "filesystem": fs_profile,
                "network": "restricted", "managed_config_included": True,
                "canary_read_denied": denied, "canary_exit_code": checker.returncode,
                "tool_inventory_known": False, "scope": "development_permission_check_not_experiment"}
            if not denied:
                raise SDKIsolationError("OS-enforced canary read denial could not be verified")
            self.process = await asyncio.create_subprocess_exec("node", str(root / "src/sdk_bridge.mjs"),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
            return self
        except BaseException:
            await self.__aexit__(None, None, None)
            raise
        finally:
            canary.unlink(missing_ok=True)

    async def __aexit__(self, exc_type, exc, traceback):
        if self.process is not None:
            if self.process.returncode is None:
                try:
                    await asyncio.wait_for(self._request({"op": "close"}), 5)
                    await asyncio.wait_for(self.process.wait(), 5)
                except (Exception, asyncio.CancelledError):
                    try:
                        os.killpg(self.process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    await self.process.wait()
            self.process = None
        if self.work_root:
            shutil.rmtree(self.work_root, ignore_errors=True)
            self.work_root = None

    async def _request(self, request: dict) -> dict:
        if self.process is None or self.process.returncode is not None:
            raise SDKIsolationError("SDK bridge is closed")
        self.process.stdin.write((json.dumps(request) + "\n").encode())
        await self.process.stdin.drain()
        line = await self.process.stdout.readline()
        if not line:
            raise SDKIsolationError("SDK bridge closed without returning a result")
        return json.loads(line)

    async def start_session(self, instructions: str, role: str, trace_dir: Path):
        async with self._active:
            response = await self._request({"op": "start", "instructions": instructions, "role": role})
        if "session_key" not in response:
            raise SDKIsolationError("Cannot start SDK role session")
        trace_dir = Path(trace_dir)
        trace_dir.mkdir(parents=True, exist_ok=True)
        _dump(trace_dir / "permission-evidence.json", self.permission_evidence)
        _dump(trace_dir / "session.json", {"role": role, "sdk_version": PINNED_VERSION,
            "sdk_language": "typescript", "cli_version": PINNED_VERSION,
            "ephemeral": False, "persistence_reason": "official SDK uses exec resume for role history",
            "instructions_sha256": hashlib.sha256(instructions.encode()).hexdigest(),
            "tool_inventory_verified": False, "development_only": self.development_probe})
        return Session(self, response["session_key"], trace_dir)


class Session:
    def __init__(self, adapter, session_key, trace_dir):
        self.adapter, self.session_key, self.trace_dir = adapter, session_key, trace_dir
        self.steps = 0
        self.broken = False
        self.thread_id = None
        self.selected_model = None
        self._previous_usage = None

    async def step(self, prompt: str, output_schema: dict, timeout_seconds: float = 90) -> dict:
        if self.broken:
            raise SDKIsolationError("Session is unusable after an interrupted/failed turn")
        async with self.adapter._active:
            self.steps += 1
            began = time.monotonic()
            events_path = self.trace_dir / f"step-{self.steps:03d}.events.jsonl"
            try:
                observed = await asyncio.wait_for(self.adapter._request({"op": "step",
                    "session_key": self.session_key, "prompt": prompt, "output_schema": output_schema,
                    "timeout_seconds": timeout_seconds}), timeout_seconds + 15)
            except (Exception, asyncio.CancelledError) as exc:
                self.broken = True
                # A killed request leaves protocol alignment uncertain; close this worker.
                await self.adapter.__aexit__(None, None, None)
                result = {"text": None, "usage": None, "duration_seconds": time.monotonic()-began,
                    "thread_id": self.thread_id, "turn_id": None, "selected_model": self.selected_model,
                    "events_path": str(events_path.resolve()), "status": "failed", "error_type": type(exc).__name__}
                events_path.write_text("")
                _dump(self.trace_dir / f"step-{self.steps:03d}.result.json", result)
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise SDKExecutionError("SDK bridge failed; usage remains unknown", result) from exc
            events = observed.pop("events", [])
            with events_path.open("w") as handle:
                for event in events:
                    handle.write(json.dumps(event, ensure_ascii=False)+"\n")
            self.thread_id = observed.get("thread_id")
            self.selected_model = observed.get("selected_model")
            raw_usage = observed.get("usage")
            usage = cumulative_usage_delta(raw_usage, self._previous_usage)
            if raw_usage is not None:
                self._previous_usage = raw_usage
            result = {"text": observed.get("text"), "usage": usage,
                "duration_seconds": time.monotonic()-began, "thread_id": self.thread_id,
                "turn_id": observed.get("turn_id"), "selected_model": self.selected_model,
                "events_path": str(events_path.resolve()), "status": observed.get("status", "failed")}
            _dump(self.trace_dir / f"step-{self.steps:03d}.metadata.json", {
                k:v for k,v in observed.items() if k not in {"text", "usage"}} | {"raw_cumulative_usage": raw_usage, "usage_semantics": "per_step_difference_of_observed_thread_total"})
            if result["status"] != "completed":
                self.broken = True
                result["error_type"] = observed.get("error_type", "sdk_failure")
                _dump(self.trace_dir / f"step-{self.steps:03d}.result.json", result)
                raise SDKExecutionError("SDK role turn failed", result)
            return result
