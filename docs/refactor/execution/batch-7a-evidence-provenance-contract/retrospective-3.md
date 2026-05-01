# Retrospective 3 — Evidence / Provenance Contract Foundation

## A. Plan adherence

- [x] pass — Implemented the Claude-green 7A.2 typed manifest plan.
- [x] pass — Stayed within evidence export source/tests, generated-client-sensitive package schema/type smoke, import-linter config, and batch execution docs.
- [x] pass — Did not start provenance strict parser, retention tombstones, artifact/file ownership migration, frontend evidence UI work, rerun, or human review work.
- [x] pass — Implemented behavior pins before and with the manifest migration: raw/redacted hash semantics, manifest/envelope mirror equality, OpenAPI typed manifest, and package type-smoke coverage.
- [x] pass — Preserved load-bearing decisions: no evidence ledger, no migration, no raw payload retention, no package rename, no namespace migration.

## B. Acceptance criteria

- [x] pass — Raw and redacted exports share one top-level export shape and one typed manifest builder.
- [x] pass — `EvidenceExportManifest` is the typed runtime and OpenAPI manifest contract.
- [x] pass — Manifest is canonical for `schema_version` and `content_hash`; top-level fields are tested mirrors.
- [x] pass — Manifest declares `content_hash_input` and tests prove hashes are over the exact returned `bundle` payload, including the actual served HTTP attachment.
- [x] pass — Manifest includes export timestamp, tenant/run/trace/flow identity, export reason, exported user id, detail mode, redaction policy, redaction summary mirrors, retention summary, artifact availability summary, and provenance compatibility fields.
- [x] pass — OpenAPI and checked-in generated schema agree that manifest `flow_version` is non-null.
- [x] pass — Schema version bump from `flow-evidence-export.v2` to `flow-evidence-export.v3` is recorded in the journal with field-level changes.
- [x] pass — No criterion is marked done without code/test evidence.

## C. Behavior pins and validation

- [x] pass — All 7A.2 validation commands passed.
- [x] pass — Backend tests covered export rendering, strict export context/manifest models, service hash semantics, router reason propagation, HTTP attachment hash integrity, OpenAPI schema, and startup/import schema behavior.
- [x] pass — Frontend package checks covered the updated generated evidence export alias through package type-smoke tests.
- [x] pass — Existing warnings were deprecation warnings and not product regressions.

## D. Pre-production deletion discipline

- [x] pass — Deleted no data-preserving path in this slice.
- [x] pass — Preserved no never-shipped compatibility shim.
- [x] pass — Did not add `audit_event_id` as a permanent-null public field.
- [x] pass — Introduced no compatibility branch, dual namespace, package alias, or legacy fallback.

## E. Single source of truth

- [x] pass — Manifest owns schema/hash semantics; top-level envelope fields are compatibility mirrors with equality tests.
- [x] pass — Export attachment `bundle` is intentionally open JSON to preserve the exact hashed evidence object; the typed read-model response remains separate.
- [x] pass — The top-level redaction block remains the detailed redaction owner; manifest redaction fields are summary mirrors with equality tests.
- [x] pass — Retention and artifact availability summaries are explicitly truth-telling placeholders and defer real ownership to later slices.
- [x] pass — New manifest module has one narrow responsibility and is included in import-linter boundary checks.

## F. File splits and naming

- [x] pass — Added one narrow source file, `flow_run_evidence_export_manifest.py`, because both the renderer and API schema need the same typed manifest contract without importing each other.
- [x] pass — Added no helper/common/shared/manager module.
- [x] pass — Added no interface, protocol, factory, or pass-through service.

## G. Comments and readability

- [x] pass — Added no production comments.
- [x] pass — Runtime note strings are short and do not mention internal batch or plan labels.
- [x] pass — Names use evidence/export domain language rather than generic terms.

## H. Test quality

- [x] pass — Tests assert public behavior and typed contract semantics rather than private helper calls.
- [x] pass — Added a strict-model validation test so unknown manifest fields fail.
- [x] pass — Added generated-client/type-smoke coverage instead of hand-waving the TypeScript contract.

## I. Boundary discipline

- [x] pass — Pydantic contract models live at the evidence export boundary, not in domain persistence or HTTP router code.
- [x] pass — Router remains the HTTP/audit adapter and only passes validated export reason into the service.
- [x] pass — Application service owns user context for export manifest context.
- [x] pass — No ORM, migration, Celery, or runtime worker behavior changed.

## J. Scope and risk

- [x] pass — Touched only Flow evidence export source/tests, generated-client-sensitive package schema/type smoke, import-linter config, and batch docs.
- [x] pass — Carry-forward risks are recorded in the journal.
- [x] pass — Official Batch 8 has not started.

## Final gate

- Fail count: 0
- Gate: GREEN
