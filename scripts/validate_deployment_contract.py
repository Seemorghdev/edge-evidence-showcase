#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str, expected: int = 0) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(args),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == expected, (
        args,
        completed.returncode,
        completed.stdout,
        completed.stderr,
    )
    return completed


def main() -> int:
    contract = json.loads(
        (ROOT / "deploy" / "deployment-contract.json").read_text(encoding="utf-8")
    )
    assert contract["schema"] == "edge-evidence-showcase-deployment.v1"
    assert contract["stage"] == "service-owned-terraform-planning"
    assert contract["deployment_authorized"] is False
    assert contract["credential_source"] == "local-executor-only"
    assert contract["image"]["required_digest"] is True
    assert contract["image"]["same_image_required_for_all_providers"] is True
    assert contract["providers"]["heroku"]["preexisting_app_required"] is True
    assert contract["execution_guards"] == {
        "SHOWCASE_DEPLOYMENT_APPROVED": "1",
        "SHOWCASE_DEPLOYMENT_EXECUTOR": "local",
    }
    assert contract["terraform"] == {
        "path": "infra/cloud-run",
        "terraform_version": "1.16.0",
        "provider_source": "hashicorp/google",
        "provider_version": "7.46.0",
        "backend_configured": False,
        "mock_provider_tests": True,
        "real_provider_plan_authorized": False,
        "real_provider_apply_authorized": False,
        "allowed_resource_types": [
            "google_cloud_run_v2_service",
            "google_cloud_run_v2_service_iam_member",
        ],
    }

    workflow_path = ROOT / ".github" / "workflows" / "deployment-readiness.yml"
    workflow = workflow_path.read_text(encoding="utf-8")
    for forbidden in (
        "secrets.",
        "id-token: write",
        "google-github-actions/auth",
        "gcloud run deploy",
        "api.heroku.com",
        "docker push",
        "terraform plan -out",
        "terraform apply",
    ):
        assert forbidden not in workflow
    for required in (
        "contents: read",
        'terraform_version: "1.16.0"',
        "terraform -chdir=infra/cloud-run init -backend=false -input=false",
        "terraform -chdir=infra/cloud-run validate",
        "terraform -chdir=infra/cloud-run test -no-color",
        "infra/cloud-run/policy/check_source.py",
        "destructive-plan.json",
    ):
        assert required in workflow
    assert not (ROOT / ".github" / "workflows" / "deploy-live.yml").exists()

    cloud_run = (ROOT / "deploy" / "cloud-run.sh").read_text(encoding="utf-8")
    heroku = (ROOT / "deploy" / "heroku.sh").read_text(encoding="utf-8")
    runbook = (ROOT / "deploy" / "README.md").read_text(encoding="utf-8")

    for script in (cloud_run, heroku):
        assert "SHOWCASE_DEPLOYMENT_APPROVED" in script
        assert "SHOWCASE_DEPLOYMENT_EXECUTOR" in script
        assert "local" in script
    assert "@sha256:" in cloud_run
    assert "SHOWCASE_ALLOW_CREATE_CLOUD_RUN_SERVICE" in cloud_run
    assert "SHOWCASE_ALLOW_PUBLIC_INVOCATION" in cloud_run
    assert "app creation is a separate owner-gated action" in heroku
    assert "local credentialed executor" in runbook
    assert "Do not paste values into chat" in runbook
    assert "infra/cloud-run/EXECUTION_PACKET.md" in runbook

    infrastructure = ROOT / "infra" / "cloud-run"
    for relative in (
        "README.md",
        "EXECUTION_PACKET.md",
        "main.tf",
        "outputs.tf",
        "variables.tf",
        "versions.tf",
        "terraform.tfvars.example",
        "tests/cloud_run.tftest.hcl",
        "policy/check_source.py",
        "policy/check_plan.py",
        "policy/fixtures/private-plan.json",
        "policy/fixtures/public-plan.json",
        "policy/fixtures/destructive-plan.json",
    ):
        assert (infrastructure / relative).is_file(), relative

    _run(sys.executable, "infra/cloud-run/policy/check_source.py")
    _run(
        sys.executable,
        "infra/cloud-run/policy/check_plan.py",
        "infra/cloud-run/policy/fixtures/private-plan.json",
        "--expect-public",
        "false",
    )
    _run(
        sys.executable,
        "infra/cloud-run/policy/check_plan.py",
        "infra/cloud-run/policy/fixtures/public-plan.json",
        "--expect-public",
        "true",
    )
    _run(
        sys.executable,
        "infra/cloud-run/policy/check_plan.py",
        "infra/cloud-run/policy/fixtures/destructive-plan.json",
        "--expect-public",
        "false",
        expected=1,
    )

    print("deployment and service-owned Terraform preparation validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
