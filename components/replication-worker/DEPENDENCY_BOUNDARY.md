# Dependency boundary

Component: `replication-worker`
Source: private canonical source (identity withheld)
Policy: `generated-product/upstream-first`
Entry point: `apps.replication_worker.cli:main`

## Included candidate paths

- `apps/__init__.py`
- `apps/_cli.py`
- `apps/replication_worker/__init__.py`
- `apps/replication_worker/cli.py`
- `apps/replication_worker/target_config.py`
- `packages/__init__.py`
- `packages/agent_contracts/__init__.py`
- `packages/agent_contracts/canonical.py`
- `packages/agent_contracts/model.py`
- `packages/agent_contracts/policy.py`
- `packages/agent_contracts/processor.py`
- `packages/agent_contracts/replication.py`
- `packages/database/__init__.py`
- `packages/database/migrations.py`
- `packages/database/replication_target_migration_v10.py`
- `packages/replication/__init__.py`
- `packages/replication/action/__init__.py`
- `packages/replication/action/implementation_identity.py`
- `packages/replication/action/manifest.py`
- `packages/replication/action/projections.py`
- `packages/replication/adapters/__init__.py`
- `packages/replication/adapters/gcs/__init__.py`
- `packages/replication/adapters/gcs/model.py`
- `packages/replication/adapters/gcs/target.py`
- `packages/replication/adapters/nfs/__init__.py`
- `packages/replication/adapters/nfs/filesystem.py`
- `packages/replication/adapters/nfs/inspection.py`
- `packages/replication/adapters/nfs/model.py`
- `packages/replication/adapters/nfs/target.py`
- `packages/replication/contracts/__init__.py`
- `packages/replication/contracts/model.py`
- `packages/replication/contracts/target.py`
- `packages/replication/core/__init__.py`
- `packages/replication/core/authority.py`
- `packages/replication/core/source.py`
- `packages/replication/core/worker.py`
- `packages/replication/worker.py`
- `packages/replication/model.py`
- `tests/unit/test_replication_gcs.py`
- `tests/unit/test_replication_target_config.py`
- `tests/unit/test_replication_target_contract.py`

## External prerequisites

- None

This repository is a generated product. Authoritative changes are upstream-first.
The exact private source binding is intentionally withheld from public bytes and
retained only in private validation evidence.
