# Dependency boundary

Component: `processor-worker`
Source: private canonical source (identity withheld)
Policy: `generated-product/upstream-first`
Entry point: `apps.processor_worker.cli:main`

## Included candidate paths

- `apps/__init__.py`
- `apps/_cli.py`
- `apps/edge_agent/__init__.py`
- `apps/edge_agent/finalize.py`
- `apps/edge_agent/lock.py`
- `apps/edge_agent/migration_history.py`
- `apps/edge_agent/process.py`
- `apps/edge_agent/register.py`
- `apps/edge_agent/staging.py`
- `apps/edge_agent/verification.py`
- `apps/processor_worker/__init__.py`
- `apps/processor_worker/cli.py`
- `apps/processor_worker/worker.py`
- `packages/__init__.py`
- `packages/agent_contracts/__init__.py`
- `packages/agent_contracts/canonical.py`
- `packages/agent_contracts/model.py`
- `packages/agent_contracts/policy.py`
- `packages/agent_contracts/processor.py`
- `packages/agent_contracts/replication.py`
- `packages/processing/__init__.py`
- `packages/processing/fingerprint.py`
- `packages/database/__init__.py`
- `packages/database/migrations.py`
- `packages/database/replication_target_migration_v10.py`
- `tests/unit/test_processor_pilot.py`
- `tests/unit/test_processor_worker.py`

## External prerequisites

- `ffmpeg`
- `ffprobe`

This repository is a generated product. Authoritative changes are upstream-first.
The exact private source binding is intentionally withheld from public bytes and
retained only in private validation evidence.
