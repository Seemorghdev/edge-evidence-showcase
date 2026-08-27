#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    contract = json.loads(
        (ROOT / "deploy" / "deployment-contract.json").read_text(encoding="utf-8")
    )
    assert contract["schema"] == "edge-evidence-showcase-deployment.v1"
    assert contract["stage"] == "credential-free-planning"
    assert contract["deployment_authorized"] is False
    assert contract["credential_source"] == "local-executor-only"
    assert contract["image"]["required_digest"] is True
    assert contract["image"]["same_image_required_for_all_providers"] is True
    assert contract["providers"]["heroku"]["preexisting_app_required"] is True
    assert contract["execution_guards"] == {
        "SHOWCASE_DEPLOYMENT_APPROVED": "1",
        "SHOWCASE_DEPLOYMENT_EXECUTOR": "local",
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
    ):
        assert forbidden not in workflow
    assert "contents: read" in workflow
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

    print("deployment preparation contract validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
