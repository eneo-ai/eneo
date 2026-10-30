# Frontend State Standard

Frontend state has one owner. Components may project and edit that state, but
they must not silently create a second lifecycle or backend contract.

Flag:

- duplicated state between drivers, services, stores, and components;
- duplicated derived values instead of one named derivation owner;
- components that perform domain orchestration or transport work;
- side effects in `load` or `$effect` that compensate for unclear ownership;
- manual copies of backend request, response, status, or error types;
- `any`, `as any`, `@ts-ignore`, and unvalidated type assertions.

`unknown` is appropriate for untrusted boundary data. Validate or narrow it
before application state, rendering, or behavior depends on it.

Prefer explicit props for local ownership. Flag a prop chain only when its depth
or fan-out obscures a shared lifetime and change owner; introduce context or a
store only when that shared boundary is real.

Use generated API types as the source of truth. A frontend adapter may narrow or
map a generated contract into view state, but it must not widen finite backend
states or reintroduce private fields.

Reuse an existing product primitive when behavior and ownership match. Extract
a new shared primitive only after repeated stable behavior proves a real shared
concept; do not create a component library around speculative reuse.

For each frontend recommendation, name the canonical state owner, generated type
source, side-effect boundary, protected behavior, and reviewability impact.
