from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_C07 = (
    "A separate reference-platform evidence track has an accepted zero-mutation GKE "
    "external-exposure observation proving the reviewed synthetic three-service workload "
    "and bounded same-origin HTTP journey under a stable provider state; private provider "
    "coordinates and retained evidence are not published here."
)
_C08 = (
    "The accepted GKE observation is not proof of final stable-address ownership, DNS, "
    "TLS/HTTPS, a permanent public endpoint, production availability, performance, scale, "
    "physical evidence integration, or persistent hosted evidence authority."
)


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
    assert by_id["C07"]["statement"] == _C07
    assert by_id["C08"]["status"] == "limitation"
    assert by_id["C08"]["statement"] == _C08
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


def test_portfolio_navigation_separates_canonical_surfaces_from_legacy_exports() -> None:
    components = json.loads(
        (ROOT / "PUBLIC_COMPONENTS.json").read_text(encoding="utf-8")
    )
    surfaces = components["portfolio_surfaces"]
    assert [item["name"] for item in surfaces] == [
        "processor",
        "replication",
        "reference-platform",
        "infrastructure",
        "operations",
        "showcase",
    ]

    by_name = {item["name"]: item for item in surfaces}
    private_names = {
        "processor",
        "replication",
        "reference-platform",
        "operations",
    }
    public_names = {"infrastructure", "showcase"}
    assert {
        name for name, item in by_name.items() if item["visibility"] == "private"
    } == private_names
    assert {
        name for name, item in by_name.items() if item["visibility"] == "public"
    } == public_names
    assert all(by_name[name]["public_url"] is None for name in private_names)
    assert by_name["infrastructure"]["public_url"] == (
        "https://github.com/Seemorghdev/edge-evidence-infrastructure"
    )
    assert by_name["showcase"]["public_url"] == (
        "https://github.com/Seemorghdev/edge-evidence-showcase"
    )

    legacy = {item["name"]: item for item in components["legacy_public_exports"]}
    assert set(legacy) == {"processor-worker", "replication-worker"}
    assert all(
        "legacy generated/export surface" in item["relationship"]
        for item in legacy.values()
    )
    assert all("not the canonical" in item["relationship"] for item in legacy.values())

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for repository in (
        "edge-evidence-processor",
        "edge-evidence-replication",
        "edge-evidence-reference-platform",
        "edge-evidence-operations",
    ):
        assert f"](https://github.com/Seemorghdev/{repository})" not in readme
        assert repository in readme

    for repository in (
        "edge-evidence-infrastructure",
        "edge-evidence-processor-worker",
        "edge-evidence-replication-worker",
    ):
        assert f"https://github.com/Seemorghdev/{repository}" in readme

    assert "publication state only" in readme
    assert "legacy generated/export surfaces" in readme
