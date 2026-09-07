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
        "C07",
        "C08",
    ]
    by_id = {item["id"]: item for item in claims["claims"]}
    assert by_id["C04"]["status"] == "synthetic-only"
    assert "separately installed generated workers" in by_id["C04"]["statement"]
    assert by_id["C05"]["status"] == "private-deployment-verified"
    assert "owner-authorized private Cloud Run deployment" in by_id["C05"]["statement"]
    assert "not deployment authority" in by_id["C05"]["statement"]
    assert by_id["C06"]["status"] == "limitation"
    assert "is not physical NAS" in by_id["C06"]["statement"]
    assert by_id["C07"]["status"] == "cross-repo-private-evidence"
    assert "accepted zero-mutation GKE external-exposure observation" in by_id["C07"]["statement"]
    assert "private provider coordinates" in by_id["C07"]["statement"]
    assert by_id["C08"]["status"] == "limitation"
    assert "DNS" in by_id["C08"]["statement"]
    assert "TLS/HTTPS" in by_id["C08"]["statement"]
    assert "production availability" in by_id["C08"]["statement"]
    prohibited = " ".join(claims["prohibited"]).lower()
    for marker in (
        "production",
        "physical nas",
        "performance",
        "persistent hosted evidence authority",
        "independent provider",
        "scheduler operations",
        "dns",
        "tls/https",
        "private topology",
        "terraform state",
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
