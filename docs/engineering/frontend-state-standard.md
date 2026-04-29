# Frontend State Standard

Frontend state must have one owner.

Flag:

- duplicated state between drivers, services, stores, and components
- duplicated derived values
- prop drilling that should be context or store
- components doing domain orchestration
- side effects in `load`
- `$effect` used to compensate for unclear ownership
- manual duplicate backend types
- `any`, `unknown`, `as any`, and `@ts-ignore`

Reusable primitives should exist for repeated product concepts such as status pills, uploaders, editors, artifact/evidence viewers, error banners, empty/loading states, and phase indicators.

For every frontend recommendation, include canonical state owner, generated type source, derived value owner, side-effect boundary, component responsibility, tests required, and reviewability impact.
