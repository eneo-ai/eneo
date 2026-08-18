# AI-byggaren — design source and build report

The AI builder's design was delivered as a Claude Design handoff. These three
documents are the durable part of it and live here so anyone continuing the work
can read them without the prototype.

| File | What it is |
| --- | --- |
| `Byggspec.md` | The design specification: measurements per screen, states, breakpoints, wording that must not drift, and the numbered deviation lists (§7, §10, §14–17) each build was audited against. |
| `REPORT.md` | What was actually built, slice by slice, with every deviation from the spec and the reason for it. Read this before assuming the build is a pixel copy — several deviations are deliberate, because the spec's prototype could show data the real contract does not carry. |
| `HANDOFF.md` | The designer's own orientation notes for the handoff. |

Not committed here: the prototype (`AI-byggaren.dc.html` and its assets) and
about 12 MB of screenshots. They are a snapshot of the designer's tool that goes
stale as soon as the spec moves, and the two documents above carry everything a
reader needs. Ask the owner if you want the prototype; it is kept outside the
repository.

## Where the code is

`frontend/apps/web/src/lib/features/flows/ai-builder`. The backend contracts it
reads are in `backend/src/eneo/flows/ai_builder`; `REPORT.md` names the ones that
were added or changed for this surface and why.
