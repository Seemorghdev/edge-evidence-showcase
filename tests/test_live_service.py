from __future__ import annotations

import importlib.util
import json
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


serve_showcase = _load("serve_showcase", ROOT / "scripts" / "serve_showcase.py")
smoke_live = _load("smoke_live", ROOT / "scripts" / "smoke_live.py")


def _request(port: int, path: str) -> tuple[int, dict[str, object]]:
    with urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))
        assert isinstance(payload, dict)
        return response.status, payload


def _server(monkeypatch):
    monkeypatch.setattr(serve_showcase, "_runtime_ready", lambda: (True, []))
    monkeypatch.setattr(serve_showcase, "_DEMO_CACHE", None)
    calls = {"count": 0}

    def run_demo():
        calls["count"] += 1
        return {
            "status": "pass",
            "run_fingerprint": "sha256:test",
            "constraints": {
                "synthetic_inputs_only": True,
                "credentials_required": False,
                "external_service_required": False,
                "publication_performed": False,
                "persistent_evidence_authority_claimed": False,
            },
        }

    monkeypatch.setattr(serve_showcase, "_run_demo_once", run_demo)
    server = serve_showcase.ShowcaseServer(
        ("127.0.0.1", 0),
        serve_showcase.ShowcaseHandler,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, calls


def test_service_health_and_synthetic_demo(monkeypatch) -> None:
    server, thread, calls = _server(monkeypatch)
    try:
        port = server.server_address[1]
        status, root = _request(port, "/")
        assert status == 200
        assert root["mode"] == "synthetic-stateless"
        assert root["scope"] == {
            "accepts_user_evidence": False,
            "camera_access": False,
            "filesystem": "ephemeral-per-instance",
            "persistent_evidence_authority": False,
            "synthetic_inputs_only": True,
        }
        assert _request(port, "/healthz")[1]["status"] == "ok"
        assert _request(port, "/readyz")[1]["status"] == "ready"
        demo = _request(port, "/api/demo")[1]
        assert demo["status"] == "pass"
        assert demo["cached"] is False
        summary = demo["summary"]
        assert isinstance(summary, dict)
        constraints = summary["constraints"]
        assert isinstance(constraints, dict)
        assert constraints["synthetic_inputs_only"] is True
        repeated = _request(port, "/api/demo")[1]
        assert repeated["cached"] is True
        assert calls["count"] == 1
        result = smoke_live._validate_target(
            f"http://127.0.0.1:{port}",
            timeout=5,
            allow_http=True,
        )
        assert result["run_fingerprint"] == "sha256:test"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_service_rejects_inputs(monkeypatch) -> None:
    server, thread, _calls = _server(monkeypatch)
    try:
        port = server.server_address[1]
        try:
            _request(port, "/api/demo?source=private")
        except HTTPError as exc:
            assert exc.code == 400
        else:
            raise AssertionError("query input was not rejected")
        request = Request(
            f"http://127.0.0.1:{port}/api/demo",
            method="POST",
            data=b"{}",
        )
        try:
            urlopen(request, timeout=5)
        except HTTPError as exc:
            assert exc.code == 405
        else:
            raise AssertionError("request body was not rejected")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
