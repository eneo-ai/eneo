# Flows documentation

Three documents cover Eneo Flows. Read them in this
order; each says what it owns, so nothing is documented twice.

| Read this | When you need |
| --- | --- |
| [Flow developer quickstart](./flow-developer-quickstart.md) | The core data model, the published runtime contract, and what a step may take as input and produce as output. Start here. |
| [Flow architecture](./architecture.md) | Module ownership, runtime journeys, the policy decisions that are settled, and which guard tests enforce them. |
| [Flow package layout](./package-layout.md) | Where a root-level Flow module belongs. Read before adding or moving one. |

## Current authority

These pages describe the current implementation. ADRs in [`docs/adr`](../adr/)
record why earlier decisions were made, but may be historical. The
[Flow launch scope and lifecycle ADR](../adr/flow-launch-scope-and-lifecycle.md)
is explicitly superseded where it describes the removed retention-governance
and partial-rerun surfaces.

## Where the code is

- Backend: `backend/src/eneo/flows` — layered per the package layout page.
- Frontend: `frontend/apps/web/src/lib/features/flows`.
- Portable packages: `backend/src/eneo/flow_packages`, deliberately outside
  `eneo.flows`.
- AI Builder: a stacked extension that compiles into the same core draft model;
  it does not own a second runtime.

## Delivery record

The tidy plan and final review report under `.claude` record the delivery
phases and measured validation. They are evidence, not additional architecture
owners.
