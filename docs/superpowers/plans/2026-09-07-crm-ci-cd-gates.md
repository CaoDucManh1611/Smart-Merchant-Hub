# CRM CI/CD quality gates

## Goal

Make the repository prove migrations, backend/frontend tests, builds and compose health before any future commit/push is treated as releasable.

## Implementation tasks

- Update `.github/workflows/ci.yml` so backend setup runs `alembic upgrade head`, then backend tests; add frontend `npm test` before build.
- Add a disposable PostgreSQL migration/current check and a compose health smoke job that exercises backend `/health` and frontend readiness.
- Keep Docker image builds in CI and fail on `git diff --check`, migration drift or missing test commands.
- Update `.github/workflows/cd.yml` to publish immutable SHA-tagged images, run migrations before rollout, verify backend/frontend health, and fail without promoting `latest` when rollout checks fail.
- Add a local `scripts/ci-smoke.ps1` or documented equivalent that mirrors the gates without requiring a GitHub runner.

## Tests and verification

- Validate workflow YAML syntax and action commands locally.
- Run backend full pytest, frontend full Node suite, `python -m compileall -q app alembic tests`, Alembic upgrade/current, frontend production build, Docker builds and compose smoke when Docker is available.
- Record failures as actionable CI output; never hide them behind `continue-on-error`.
