# Batch 5 Naming Decision

## Decision

Keep the frontend package name `@intric/intric-js` and the directory
`frontend/packages/intric-js` for Batch 5.

Do not ship a package rename in this batch.

Do not create:

- `@eneo/*` compatibility packages
- parallel `eneo` package directories
- thin re-export aliases from an Eneo package to the Intric package
- dual import namespaces

## Reasoning

Eneo is the desired product/platform brand going forward, but the package name
is a generated-client and consumer migration surface. Renaming it while Batch 5
is cleaning up generated type ownership would mix two different risks:

- type drift cleanup between `resources.d.ts` and `schema.d.ts`
- package identity and downstream import migration

The cleaner sequence is to make `@intric/intric-js` less drift-prone first, then
rename only after a consumer inventory and migration plan.

## Consumer Impact

Known internal consumers import `@intric/intric-js` from:

- `frontend/apps/web/src`
- `frontend/packages/ui/src`
- `frontend/packages/intric-js/src` JSDoc references

External consumer status is not proven in this workspace. Silent package rename
would be risky if any downstream code consumes the package.

## Future Rename Sequence If Approved

1. Inventory internal and external consumers.
2. Decide whether the package should be renamed, dual-published for a migration
   window, or kept stable.
3. If renamed, create a dedicated package migration batch or ADR with:
   - package name
   - import path migration
   - generated client publishing impact
   - changelog/release notes
   - deprecation/removal timeline if dual publish is required
4. Keep generated schema and resource alias changes separate from package rename
   churn.

## Explicit Non-Goal

No package rename ships in Batch 5 unless the user separately approves that
scope expansion.
