#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

DIGEST_RE = re.compile(r"@sha256:[0-9a-f]{64}$")
SERVICE = "google_cloud_run_v2_service.showcase"
PUBLIC_IAM = "google_cloud_run_v2_service_iam_member.public_invoker[0]"


def _first(value: Any, label: str) -> dict[str, Any]:
    if isinstance(value, list) and value:
        item = value[0]
    elif isinstance(value, dict):
        item = value
    else:
        raise AssertionError(f"{label} must contain one block")
    if not isinstance(item, dict):
        raise AssertionError(f"{label} block must be an object")
    return item


def validate(plan: dict[str, Any], expect_public: bool) -> None:
    changes = plan.get("resource_changes")
    assert isinstance(changes, list), "resource_changes must be a list"

    by_address = {item["address"]: item for item in changes}
    expected = {SERVICE}
    if expect_public:
        expected.add(PUBLIC_IAM)
    assert set(by_address) == expected, set(by_address)

    for address, item in by_address.items():
        resource_type = item.get("type")
        assert resource_type in {
            "google_cloud_run_v2_service",
            "google_cloud_run_v2_service_iam_member",
        }, resource_type
        actions = item["change"]["actions"]
        assert actions in (["create"], ["update"], ["no-op"]), (address, actions)
        assert "delete" not in actions, (address, actions)

    service = by_address[SERVICE]["change"]["after"]
    assert service["deletion_protection"] is True
    assert service["ingress"] == "INGRESS_TRAFFIC_ALL"

    template = _first(service["template"], "template")
    assert template["service_account"].endswith(".iam.gserviceaccount.com")
    assert template["timeout"] == "120s"
    assert template["max_instance_request_concurrency"] == 1

    scaling = _first(template["scaling"], "scaling")
    assert scaling["min_instance_count"] == 0
    assert scaling["max_instance_count"] == 3

    container = _first(template["containers"], "containers")
    assert DIGEST_RE.search(container["image"])
    limits = _first(container["resources"], "resources")["limits"]
    assert limits == {"cpu": "1", "memory": "512Mi"}

    if expect_public:
        iam = by_address[PUBLIC_IAM]["change"]["after"]
        assert iam["role"] == "roles/run.invoker"
        assert iam["member"] == "allUsers"

    print(
        "cloud run plan policy validated: "
        + ("public invocation approved" if expect_public else "private invocation")
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan_json", type=Path)
    parser.add_argument("--expect-public", choices=("true", "false"), required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan_json.read_text(encoding="utf-8"))
    validate(plan, expect_public=args.expect_public == "true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
