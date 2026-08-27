from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_deployment_contract_is_credential_free_and_local_executor_only() -> None:
    contract = json.loads(
        (ROOT / "deploy" / "deployment-contract.json").read_text(encoding="utf-8")
    )
    assert contract["stage"] == "credential-free-planning"
    assert contract["deployment_authorized"] is False
    assert contract["credential_source"] == "local-executor-only"
    assert contract["providers"]["heroku"]["preexisting_app_required"] is True
    assert contract["image"]["required_digest"] is True
    assert contract["image"]["same_image_required_for_all_providers"] is True


def test_deployment_preparation_validator_passes() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/validate_deployment_contract.py"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "deployment preparation contract validated" in completed.stdout
