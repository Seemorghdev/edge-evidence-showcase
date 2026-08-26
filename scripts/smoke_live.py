#!/usr/bin/env python3
"""Smoke-test one or more public synthetic showcase deployments."""

from __future__ import annotations

import argparse
import json
import ssl
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _get_json(base_url: str, path: str, timeout: int) -> dict[str, Any]:
    request = Request(
        base_url.rstrip("/") + path,
        headers={
            "Accept": "application/json",
            "User-Agent": "edge-evidence-public-smoke/1",
        },
    )
    try:
        with urlopen(
            request,
            timeout=timeout,
            context=ssl.create_default_context(),
        ) as response:
            if response.status != 200:
                raise RuntimeError(f"{path} returned HTTP {response.status}")
            payload = json.loads(response.read().decode("utf-8"))
    except (
        HTTPError,
        URLError,
        TimeoutError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise RuntimeError(f"{path} request failed") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path} did not return a JSON object")
    return payload


def _validate_target(
    base_url: str,
    timeout: int,
    allow_http: bool,
) -> dict[str, object]:
    parsed = urlsplit(base_url)
    allowed_schemes = {"http", "https"} if allow_http else {"https"}
    if (
        parsed.scheme not in allowed_schemes
        or not parsed.netloc
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("target URL must be an absolute HTTPS origin")
    root = _get_json(base_url, "/", timeout)
    health = _get_json(base_url, "/healthz", timeout)
    ready = _get_json(base_url, "/readyz", timeout)
    demo = _get_json(base_url, "/api/demo", timeout)
    if root.get("mode") != "synthetic-stateless" or root.get("status") != "ready":
        raise RuntimeError("service document boundary mismatch")
    if health.get("status") != "ok" or ready.get("status") != "ready":
        raise RuntimeError("health boundary mismatch")
    if demo.get("status") != "pass" or demo.get("mode") != "synthetic-stateless":
        raise RuntimeError("synthetic demo did not pass")
    summary = demo.get("summary")
    if not isinstance(summary, dict) or summary.get("status") != "pass":
        raise RuntimeError("synthetic summary did not pass")
    constraints = summary.get("constraints")
    if not isinstance(constraints, dict):
        raise RuntimeError("synthetic constraints are missing")
    required = {
        "synthetic_inputs_only": True,
        "credentials_required": False,
        "external_service_required": False,
        "publication_performed": False,
        "persistent_evidence_authority_claimed": False,
    }
    if any(constraints.get(key) is not value for key, value in required.items()):
        raise RuntimeError("synthetic constraints changed")
    fingerprint = summary.get("run_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint.startswith("sha256:"):
        raise RuntimeError("synthetic fingerprint is missing")
    return {
        "host": parsed.netloc,
        "status": "pass",
        "run_fingerprint": fingerprint,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        action="append",
        required=True,
        help="public deployment URL; repeat for multiple targets",
    )
    parser.add_argument("--timeout", type=int, default=115)
    parser.add_argument(
        "--allow-http",
        action="store_true",
        help="allow localhost HTTP for tests only",
    )
    args = parser.parse_args()
    if not 5 <= args.timeout <= 120:
        parser.error("--timeout must be between 5 and 120 seconds")
    results = [
        _validate_target(url, args.timeout, args.allow_http)
        for url in args.url
    ]
    fingerprints = {item["run_fingerprint"] for item in results}
    if len(fingerprints) != 1:
        raise RuntimeError("public deployments produced different fingerprints")
    print(
        _canonical(
            {
                "schema_version": 1,
                "status": "pass",
                "shared_run_fingerprint": next(iter(fingerprints)),
                "targets": results,
            }
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"public smoke failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
