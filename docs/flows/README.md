# Flows documentation

Three documents cover Eneo Flows. Read them in this
order; each says what it owns, so nothing is documented twice.

| Read this | When you need |
| --- | --- |
| [Flow developer quickstart](./flow-developer-quickstart.md) | The core data model, the published runtime contract, and what a step may take as input and produce as output. Start here. |
| [Flow architecture](./architecture.md) | Module ownership, runtime journeys, the policy decisions that are settled, and which guard tests enforce them. |
| [Flow package layout](./package-layout.md) | Where a root-level Flow module belongs. Read before adding or moving one. |

## Decisions live in ADRs, not here

Behaviour that was decided once and constrains everything after it is recorded
in [`docs/adr`](../adr/), and the pages above link into the specific decision
rather than restating it. The one that binds Flows today is
[Flow launch scope and lifecycle](../adr/flow-launch-scope-and-lifecycle.md):
launch scope, destructive retention activation, why Flow MCP is hard-disabled,
and how service-key rerun works. If a page here seems to contradict it, the ADR
wins and the page is stale.

## Where the code is

- Backend: `backend/src/eneo/flows` — layered per the package layout page.
- Frontend: `frontend/apps/web/src/lib/features/flows`.
- Portable packages: `backend/src/eneo/flow_packages`, deliberately outside
  `eneo.flows`.

## What is still being built

`docs/goals/eneo-flows-and-builder-9-of-10/notes/master-program.md` carries the
remaining work, the decisions that bind it, and the protocol for continuing it.
Its first table is the twelve slices that are left.
