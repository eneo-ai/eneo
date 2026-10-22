# Flows documentation

These documents cover Eneo Flows. Read them in this order; each says what it
owns, so nothing is documented twice.

| Read this | When you need |
| --- | --- |
| [Flow developer quickstart](./flow-developer-quickstart.md) | The core data model, the published runtime contract, and what a step may take as input and produce as output. Start here. |
| [Flow architecture](./architecture.md) | Module ownership, runtime journeys, the policy decisions that are settled, and which guard tests enforce them. |
| [Flow package layout](./package-layout.md) | Where a root-level Flow module belongs. Read before adding or moving one. |
| [External transcription service](./external-transcription-service.md) | Connecting a speaker identification service (such as Vemsa) for flow audio steps: how it labels a transcript, how it fails, and the speaker review rollout. |

## Current authority

These pages describe the current implementation. ADRs in [`docs/adr`](../adr/)
record why earlier decisions were made, but may be historical. The
[Flow launch scope and lifecycle ADR](../adr/flow-launch-scope-and-lifecycle.md)
is explicitly superseded where it describes the removed retention-governance
and partial-rerun surfaces.

## Where the code is

- Backend: `backend/src/eneo/flows`, layered per the package layout page.
- Authoring: the editor (`PATCH /api/v1/flows/{id}/editor/`) and the flow's
  authoring chat (`flows/application/flow_authoring_chat.py`, with its loopback
  tools in `backend/src/eneo/internal_mcp/flows.py`) both save through
  `flows/application/flow_authoring_operations.py`.
- Frontend: the new web app, `frontend/apps/web-next/src/features/flows`
  (space flows, editor and runs) and `src/features/admin/flow-settings`, routed
  from `src/app/(app)/spaces/[spaceId]/flows` and `src/app/(app)/admin`. The
  SvelteKit app has no flow screens.
- Portable packages: `backend/src/eneo/flow_packages`, deliberately outside
  `eneo.flows`.

## Delivery record

The tidy plan and final review report under `.claude` record the delivery
phases and measured validation. They are evidence, not additional architecture
owners.
