# Draft: RB-5 tracking issue (create with `gh issue create -F` or paste into GitHub)

**Title:** RB-5: backend API consistency cleanups for the typed client

Tracking issue for the API-shape cleanups identified during the web-next migration (see `docs/migration/00-overview.md`, RB-5). The new typed client (`frontend/apps/web-next/src/lib/api/`) codes against the clean shapes; every place it has to deviate is marked with a greppable `// RB-5(x)` comment, and each cleanup below removes those workarounds.

- [ ] **(a) Unify list pagination on cursor style.** `/admin/users/` and the audit-log listings still use offset pagination; everything else is `CursorPaginatedResponse` (`items`, `total_count`, `next_cursor`, `previous_cursor`).
- [ ] **(b) PATCH instead of POST for partial updates.** Assistants, services, groups, and user-by-username use POST-as-update today.
- [ ] **(c) One error envelope everywhere.** Today the body is one of: `GeneralError` (`message` + `intric_error_code`), a string `detail`, an object `detail`, or a FastAPI validation array. Converge on a single shape.
- [ ] **(d) Audit-log auth via Bearer + justification header** instead of a separate cookie session.
- [ ] **(e) Document file-size limits in the OpenAPI spec.**
- [ ] **(f) Spec accuracy: response models must produce real OpenAPI types.** First instance fixed at the source: `IntegrationKnowledgePublic.task` was annotated as the bare `Enum` base class, which generated an empty enum (`task: never`) in every consumer of the spec. When the spec under-specifies a shape, prefer fixing the backend model over patching generated types (`overrides.ts` is the fallback and each entry there is an instance of this item).

Cleanups land opportunistically when an endpoint is touched (phases 3–7); this issue is the inventory.
