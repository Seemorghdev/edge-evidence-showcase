#!/usr/bin/env python3
"""Serve the integrated showcase as a synthetic, stateless HTTP demo."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import BoundedSemaphore, Lock
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SERVICE_NAME = "edge-evidence-showcase"
MODE = "synthetic-stateless"
DEFAULT_PORT = 8080
DEFAULT_DEMO_TIMEOUT_SECONDS = 105
_DEMO_GATE = BoundedSemaphore(value=1)
_DEMO_CACHE_LOCK = Lock()
_DEMO_CACHE: dict[str, Any] | None = None
_ENV_ALLOWLIST = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR", "TEMP", "TMP")


class DemoBusy(RuntimeError):
    """A synthetic demonstration is already running in this instance."""


class DemoFailure(RuntimeError):
    """The synthetic demonstration failed closed."""


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _runtime_ready() -> tuple[bool, list[str]]:
    missing: list[str] = []
    for relative in (
        ".venv/showcase/bin/python",
        ".venv/processor/bin/python",
        ".venv/replication/bin/python",
        "demo/run_showcase.py",
    ):
        if not (ROOT / relative).is_file():
            missing.append(relative)
    for executable in ("ffmpeg", "make", "sqlite3"):
        if shutil.which(executable) is None:
            missing.append(executable)
    return not missing, missing


def _clean_environment() -> dict[str, str]:
    env = {
        name: value
        for name in _ENV_ALLOWLIST
        if (value := os.environ.get(name)) is not None
    }
    env.update(
        {
            "PYTHONNOUSERSITE": "1",
            "PIP_NO_INDEX": "1",
            "NO_PROXY": "*",
            "no_proxy": "*",
            "HTTP_PROXY": "",
            "HTTPS_PROXY": "",
            "http_proxy": "",
            "https_proxy": "",
        }
    )
    return env


def _run_demo_once() -> dict[str, Any]:
    output_name = f".demo-output-live-{uuid.uuid4().hex}"
    output_root = ROOT / output_name
    try:
        try:
            timeout = _bounded_int(
                "SHOWCASE_DEMO_TIMEOUT_SECONDS",
                DEFAULT_DEMO_TIMEOUT_SECONDS,
                10,
                115,
            )
        except ValueError as exc:
            raise DemoFailure("synthetic demo timeout configuration is invalid") from exc
        command = [
            sys.executable,
            str(ROOT / "demo" / "run_showcase.py"),
            "--output-root",
            output_name,
            "--processor-python",
            str(ROOT / ".venv" / "processor" / "bin" / "python"),
            "--replication-python",
            str(ROOT / ".venv" / "replication" / "bin" / "python"),
            "demo",
        ]
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=_clean_environment(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
        if completed.returncode != 0:
            raise DemoFailure(
                f"synthetic demo exited with status {completed.returncode}"
            )
        summary_path = output_root / "combined" / "summary.json"
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DemoFailure("synthetic demo summary is unavailable") from exc
        if not isinstance(summary, dict) or summary.get("status") != "pass":
            raise DemoFailure("synthetic demo summary did not pass")
        constraints = summary.get("constraints")
        if not isinstance(constraints, dict):
            raise DemoFailure("synthetic demo constraints are missing")
        required = {
            "synthetic_inputs_only": True,
            "credentials_required": False,
            "external_service_required": False,
            "publication_performed": False,
            "persistent_evidence_authority_claimed": False,
        }
        if any(constraints.get(key) is not value for key, value in required.items()):
            raise DemoFailure("synthetic demo constraint boundary mismatch")
        return summary
    except subprocess.TimeoutExpired as exc:
        raise DemoFailure("synthetic demo timed out") from exc
    finally:
        shutil.rmtree(output_root, ignore_errors=True)


def _get_demo_summary() -> tuple[dict[str, Any], bool]:
    global _DEMO_CACHE
    with _DEMO_CACHE_LOCK:
        if _DEMO_CACHE is not None:
            return _DEMO_CACHE, True
    if not _DEMO_GATE.acquire(blocking=False):
        raise DemoBusy("synthetic demo already running")
    try:
        with _DEMO_CACHE_LOCK:
            if _DEMO_CACHE is not None:
                return _DEMO_CACHE, True
        summary = _run_demo_once()
        with _DEMO_CACHE_LOCK:
            _DEMO_CACHE = summary
        return summary, False
    finally:
        _DEMO_GATE.release()


def _service_document() -> dict[str, object]:
    return {
        "service": SERVICE_NAME,
        "status": "ready",
        "mode": MODE,
        "scope": {
            "synthetic_inputs_only": True,
            "accepts_user_evidence": False,
            "camera_access": False,
            "persistent_evidence_authority": False,
            "filesystem": "ephemeral-per-instance",
        },
        "endpoints": {
            "health": "/healthz",
            "readiness": "/readyz",
            "synthetic_demo": "/api/demo",
        },
    }


class ShowcaseHandler(BaseHTTPRequestHandler):
    server_version = "EdgeEvidenceShowcase/1"
    sys_version = ""

    def _send_json(self, status: HTTPStatus, payload: object) -> None:
        body = _canonical(payload)
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        started = time.monotonic()
        parsed = urlsplit(self.path)
        if parsed.query or parsed.fragment:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "status": "error",
                    "error": "query parameters are not accepted",
                },
            )
            return
        if parsed.path == "/":
            self._send_json(HTTPStatus.OK, _service_document())
            return
        if parsed.path == "/healthz":
            self._send_json(
                HTTPStatus.OK,
                {"service": SERVICE_NAME, "status": "ok", "mode": MODE},
            )
            return
        if parsed.path == "/readyz":
            ready, missing = _runtime_ready()
            if ready:
                self._send_json(
                    HTTPStatus.OK,
                    {"service": SERVICE_NAME, "status": "ready", "mode": MODE},
                )
            else:
                self._send_json(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {
                        "service": SERVICE_NAME,
                        "status": "not-ready",
                        "missing_count": len(missing),
                    },
                )
            return
        if parsed.path == "/api/demo":
            try:
                summary, cached = _get_demo_summary()
            except DemoBusy:
                self._send_json(
                    HTTPStatus.TOO_MANY_REQUESTS,
                    {
                        "service": SERVICE_NAME,
                        "status": "busy",
                        "retryable": True,
                    },
                )
                return
            except DemoFailure:
                self.log_error("synthetic demo failed")
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "service": SERVICE_NAME,
                        "status": "error",
                        "retryable": True,
                    },
                )
                return
            self._send_json(
                HTTPStatus.OK,
                {
                    "service": SERVICE_NAME,
                    "status": "pass",
                    "mode": MODE,
                    "cached": cached,
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                    "summary": summary,
                },
            )
            return
        self._send_json(
            HTTPStatus.NOT_FOUND,
            {"status": "error", "error": "not found"},
        )

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._send_json(
            HTTPStatus.METHOD_NOT_ALLOWED,
            {"status": "error", "error": "read-only synthetic service"},
        )

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        path = urlsplit(self.path).path
        sys.stderr.write(
            f"{self.log_date_time_string()} {self.command} "
            f"{path} {code} {size}\n"
        )

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def log_error(self, format: str, *args: object) -> None:
        del format, args
        path = urlsplit(self.path).path
        sys.stderr.write(
            f"{self.log_date_time_string()} {self.command} "
            f"{path} error\n"
        )


class ShowcaseServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> int:
    try:
        port = _bounded_int("PORT", DEFAULT_PORT, 1, 65535)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    ready, missing = _runtime_ready()
    if not ready:
        raise SystemExit(
            f"runtime is not ready ({len(missing)} required items missing)"
        )
    server = ShowcaseServer(("0.0.0.0", port), ShowcaseHandler)
    print(
        json.dumps(
            {
                "event": "listening",
                "service": SERVICE_NAME,
                "mode": MODE,
                "port": port,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
