# Retrospective 4 — Evidence / Provenance Contract Foundation

## A. Plan adherence

- [x] pass — Implemented the Claude-green 7A.3 provenance schema versioning plan.
- [x] pass — Stayed within Flow evidence/provenance source/tests and batch execution docs.
- [x] pass — Did not start tool-call/RAG normalization, retention tombstones, artifact/file ownership migration, frontend evidence UI work, rerun, or human review work.
- [x] pass — Behavior pins landed with the parser/export changes: valid v1 parsing, corruption markers, raw/redacted marker parity, manifest status, HTTP corrupt export, and runtime writer round-trip.
- [x] pass — Preserved load-bearing decisions: no evidence ledger, no migration/backfill, no raw payload retention, no package rename, no namespace migration, and no historical reader without row proof.

## B. Acceptance criteria

- [x] pass — Attempt provenance parsing is schema-version-aware and current v1 parses normally.
- [x] pass — Missing, unsupported, unknown-top-level, invalid-type, and malformed-current provenance produce explicit corruption markers.
- [x] pass — Corrupt provenance does not crash raw or redacted evidence export.
- [x] pass — Export manifest declares `tracked`, `not_tracked`, or `corrupt` from typed parse results, not serialized marker scanning.
- [x] pass — Runtime writer output round-trips through `FlowAttemptProvenance` and is accepted by `parse_attempt_provenance` as `tracked`.
- [x] pass — No historical reader was added because no persisted historical row proof exists.
- [x] pass — No criterion is marked done without code/test evidence.

## C. Behavior pins and validation

- [x] pass — Focused backend evidence/runtime/API tests passed.
- [x] pass — Pyright, ruff, ruff-format, import-linter, anti-slippage grep, and diff-check passed.
- [x] pass — Docker validation was attempted but blocked by the local Codex approval policy before Docker execution; local/testcontainers validation passed.
- [x] pass — Added tests exercise behavior rather than private collaborator calls: parser statuses, export marker payloads, manifest status, HTTP export response, and writer/parser handshake.

## D. Pre-production deletion discipline

- [x] pass — Added no compatibility shim, fallback path, dual schema reader, or version coercion.
- [x] pass — Treated unversioned branch-local fixtures as current-v1 updates or explicit corruption cases, not historical compatibility.
- [x] pass — Did not delete any Tier B persisted/public reader in this slice.
- [x] pass — Introduced no new public historical reader without row proof.

## E. Single source of truth

- [x] pass — `flow_run_provenance.py` owns schema version constants, parser status, and corruption markers.
- [x] pass — `flow_run_evidence_bundle.py` owns persisted attempt row normalization into export payloads.
- [x] pass — `flow_run_export_json.py` owns manifest status summarization from typed parse results.
- [x] pass — Runtime writer validates through the same `FlowAttemptProvenance` owner before persistence.

## F. File splits and naming

- [x] pass — Added no new production file.
- [x] pass — Added no helper/common/shared/manager module.
- [x] pass — Added no interface, protocol, factory, or pass-through service.

## G. Comments and readability

- [x] pass — Added no production comments or docstrings that restate code.
- [x] pass — Names use evidence/provenance domain language.
- [x] pass — Claude-identified no-op/shallow-copy noise was removed.

## H. Test quality

- [x] pass — Tests pin observable evidence export and parser behavior.
- [x] pass — No internal mocks were added.
- [x] pass — No tests were deleted.
- [x] pass — The writer/parser test covers all sections appended by `_build_attempt_provenance`: LLM, RAG, runtime input, transcription, guards, template, artifacts, HTTP, and citations.

## I. Boundary discipline

- [x] pass — Pydantic provenance models remain evidence boundary models and do not leak into persistence adapters beyond JSON validation/normalization.
- [x] pass — No HTTP exceptions or router behavior were moved into domain/application code.
- [x] pass — No ORM, migration, Celery command, or data-model behavior changed.

## J. Scope and risk

- [x] pass — Touched only Flow evidence/provenance source/tests and batch execution docs.
- [x] pass — Known unrelated dirty files remain untouched and unstaged.
- [x] pass — Carry-forward risks are recorded in the journal.
- [x] pass — Official Batch 8 has not started.

## Final gate

- Fail count: 0
- Gate: GREEN
