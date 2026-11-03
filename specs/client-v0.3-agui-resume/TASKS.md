# prismal-sdk — Tasks (Client v0.3: AG-UI run input & interrupt resume)

| Field | Value |
|---|---|
| **Status** | `READY` |
| **Version** | 1.0 |
| **Date** | 2026-11-02 |
| **Author** | Ernesto Crespo |
| **Companion** | [`SPEC.md`](./SPEC.md) |

Status legend: `TODO` · `WIP` · `DONE` · `BLOCKED`. Every task is test-first (TDD). Prefix `CS3`.
Host: `prismal-server` 0.3.0 (PyPI), engine `prismal-ai` 3.22.1.

## Phase 0 — Scope, fixture, CI host

| ID | Task | SPEC | Status |
|---|---|---|---|
| CS3-00-01 | Diff host 0.2.0 → 0.3.0 and engine 3.20 → 3.22.1 for SDK impact; write this SDD | §0 | `DONE` |
| CS3-00-02 | Vendor `fixtures/agui/interrupt-resume.json` unchanged | FIX-001 | `DONE` |
| CS3-00-03 | CI `contract` job: install `prismal-server` 0.3.x from PyPI, start it in fake mode, run on PRs and dispatch (supersedes CS2-00-04's GHCR image) | CTR-001 | `DONE` |

## Phase 1 — Models and errors

| ID | Task | SPEC | Status |
|---|---|---|---|
| CS3-01-01 | `AgUiInterrupt`, `ResumeEntry`, `RunFinished.interrupts` / `is_interrupted` | INT-001..005 | `TODO` |
| CS3-01-02 | `ResumeConflictError`; map the four resume codes | ERR-001 | `TODO` |

## Phase 2 — `run_agui`

| ID | Task | SPEC | Status |
|---|---|---|---|
| CS3-02-01 | `PrismalClient.run_agui` / `AsyncPrismalClient.run_agui` | RUN-001..006 | `TODO` |
| CS3-02-02 | Replay the vendored fixture offline; parity test names `run_agui` | FIX-001, NFR-001 | `TODO` |

## Phase 3 — Contract, docs

| ID | Task | SPEC | Status |
|---|---|---|---|
| CS3-03-01 | Contract cases for resume against host 0.3 fake mode | CTR-002 | `TODO` |
| CS3-03-02 | `docs/agui.md` resume section, `docs/errors.md`, README, example, CHANGELOG | — | `TODO` |

## Phase 4 — Release

| ID | Task | SPEC | Status |
|---|---|---|---|
| CS3-04-01 | Version 0.3.0; publish workflow on `main` (trusted publishing, skip-if-published, tag after upload) | REL-001 | `TODO` |
| CS3-04-02 | CI green on the PR to `develop`; PR `develop` → `main` | — | `TODO` |
| CS3-04-03 | Register the PyPI pending publisher (owner `prismal-ai`, repo `prismal-sdk`, workflow `release.yml`, environment `pypi`) — needs the maintainer's PyPI account | REL-001 | `TODO` |

## Definition of Done (v0.3)

- Every MUST in SPEC has ≥ 1 task and ≥ 1 test; coverage ratchet holds (98 %); `mypy --strict`, ruff clean.
- Contract suite green in CI against `prismal-server` 0.3 from PyPI, with zero provider credentials.
- Import guard and parity test green; base install unchanged (`httpx` + `pydantic`).

## Changelog

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-11-02 | Ernesto Crespo | Initial; phase 0 done |
