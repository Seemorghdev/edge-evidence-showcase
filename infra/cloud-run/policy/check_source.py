#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    terraform = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(ROOT.glob("*.tf"))
    )
    resources = set(
        re.findall(r'resource\s+"([^"]+)"\s+"([^"]+)"', terraform)
    )
    expected_resources = {
        ("google_cloud_run_v2_service", "showcase"),
        ("google_cloud_run_v2_service_iam_member", "public_invoker"),
    }
    assert resources == expected_resources, resources

    required = (
        'required_version = "= 1.16.0"',
        'version = "= 7.46.0"',
        'source  = "hashicorp/google"',
        'deletion_protection = true',
        'ingress             = "INGRESS_TRAFFIC_ALL"',
        'service_account                  = var.service_account_email',
        'max_instance_request_concurrency = 1',
        'min_instance_count = 0',
        'max_instance_count = 3',
        'cpu_idle = true',
        'cpu    = "1"',
        'memory = "512Mi"',
        'path = "/readyz"',
        'path = "/healthz"',
        'count = var.allow_public_invocation ? 1 : 0',
        'role     = "roles/run.invoker"',
        'member   = "allUsers"',
    )
    for marker in required:
        assert marker in terraform, marker

    forbidden = (
        'backend "',
        'resource "google_project"',
        'resource "google_project_service"',
        'resource "google_artifact_registry_repository"',
        'resource "google_service_account"',
        'resource "google_project_iam',
        'resource "google_organization_iam',
        'resource "google_folder_iam',
        'resource "null_resource"',
        'local-exec',
        'remote-exec',
        'secret_key_ref',
        'google-beta',
        'kubernetes',
        'helm',
    )
    lowered = terraform.lower()
    for marker in forbidden:
        assert marker.lower() not in lowered, marker

    variables = (ROOT / "variables.tf").read_text(encoding="utf-8")
    for name in (
        "project_id",
        "region",
        "artifact_registry_repository",
        "image_name",
        "image_digest",
        "service_name",
        "service_account_email",
        "allow_public_invocation",
    ):
        assert f'variable "{name}"' in variables

    lock = (ROOT / ".terraform.lock.hcl").read_text(encoding="utf-8")
    assert 'provider "registry.terraform.io/hashicorp/google"' in lock
    assert 'version     = "7.46.0"' in lock
    assert 'constraints = "7.46.0"' in lock
    assert lock.count('"h1:') == 2

    example = (ROOT / "terraform.tfvars.example").read_text(encoding="utf-8")
    assert "example-project" in example
    assert "sha256:" + ("a" * 64) in example
    assert "run.app" not in example
    assert "googleusercontent.com" not in example

    packet = (ROOT / "EXECUTION_PACKET.md").read_text(encoding="utf-8")
    assert "STOP BEFORE REAL PROVIDER PLAN OR APPLY" in packet
    assert "terraform plan" in packet
    assert "terraform apply" in packet
    assert "Rollback" in packet

    print("cloud run terraform source policy validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
