from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_claims_freeze_integrated_synthetic_scope() -> None:
    claims = json.loads((ROOT / "PUBLIC_CLAIMS.json").read_text(encoding="utf-8"))
    assert claims["schema"] == "edge-evidence-public-claims.v2"
    assert [item["id"] for item in claims["claims"]] == [
        "C01",
        "C02",
        "C03",
        "C04",
        "C05",
        "C06",
    ]
    by_id = {item["id"]: item for item in claims["claims"]}
    assert by_id["C04"]["status"] == "synthetic-only"
    assert "separately installed generated workers" in by_id["C04"]["statement"]
    assert by_id["C05"]["status"] == "deployment-support"
    assert "bounded Cloud Run and Heroku controls" in by_id["C05"]["statement"]
    assert by_id["C06"]["status"] == "limitation"
    assert "not physical NAS" in by_id["C06"]["statement"]
    prohibited = " ".join(claims["prohibited"]).lower()
    for marker in (
        "production",
        "physical nas",
        "performance",
        "persistent hosted evidence authority",
        "independent provider",
        "scheduler operations",
        "exact private claim/action/worker/sqlite counts",
    ):
        assert marker in prohibited


def test_component_inventory_requires_separate_installations() -> None:
    components = json.loads(
        (ROOT / "PUBLIC_COMPONENTS.json").read_text(encoding="utf-8")
    )
    assert components["schema"] == "edge-evidence-public-components.v2"
    records = {item["name"]: item for item in components["components"]}
    assert set(records) == {"processor-worker", "replication-worker", "showcase"}
    assert records["processor-worker"]["installation"] == ".venv/processor"
    assert records["replication-worker"]["installation"] == ".venv/replication"
    assert records["processor-worker"]["bundle_path"] != records[
        "replication-worker"
    ]["bundle_path"]
