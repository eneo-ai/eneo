# AI-byggaren redesign — handoff (written 2026-08-16 21:25 by the Flows/Builder orchestrator session)

Design source: Claude Design project 44d2d638-3a2c-4c6e-98c1-1e708e6bae3e, file `AI-byggaren.dc.html`
(a copy is next to this file: template inside `<x-dc>`, component props in `data-props`, page logic in the
`data-dc-script` script; `support.js` = dc-runtime, only explains how the .dc renders — do not port it;
`_ds/` = Inter font-faces, no components). The prototype has a state rail (Skala · Tom lista · Inga frågor ·
Misslyckades · Långsam · Konflikt · Osparat · Normalläge) and screens Flöden · Skapa · Ny uppgift · Frågor ·
Bekräfta · Bygger · Granska · Mobil. Design decisions already adjudicated with the product owner (do not reopen):
phase-owned screens (Eneo förstår uppgiften → Eneo utformar planen → Du granskar innan det skapas) with the
conversation one gesture away ("Samtal" → Sheet); the confirmation card is the contract; model/reasoning/tokens
visible but quiet (never changeable from chat); per-card disclosure (no global Enkel/Avancerad); calm motion;
recommended option preselected ("Eneo föreslår") + "Jag är osäker — välj åt mig" as an explicit action;
skeleton → steps during Bygger; drafts live in the Flöden list; approval → toast + land on the flow with
Testkör / Publicera; vocabulary utkast · plan · flöde · körning · granskning.

Repo/branch: /Users/ccimen/eneo/eneo-flows-clean, branch refactor/flows-clean (HEAD 021c22e80 at writing;
moves several times a day — rebase before each gate). Work in your OWN git worktree, e.g.
`git worktree add /private/tmp/eneo-ai-builder-ui -b lane/ai-builder-ui origin/refactor/flows-clean`.
Do NOT push; the orchestrator session lands gated commits (send it the shas via cross-session message —
`ListAgents` shows it as a peer; if not visible, leave shas + branch in this folder's REPORT.md).

Current implementation to replace/deepen (read first): frontend/apps/web/src/lib/features/flows/ai-builder/
(FlowAIBuilder.svelte, …Chat/Canvas/PlanPane/StepCard/Question/RequirementsSummary/PhaseIndicator/Input/
ModelSelect/ReasoningSelect/TokenUsage/DraftRecovery/EditHost, FlowAIBuilderService.svelte.ts,
FlowAIBuilderDriver.ts, protocol.ts, structuredQuestionAnswer.ts, flowAIBuilderPlanDiff.ts …) and routes
frontend/apps/web/src/routes/(app)/spaces/[spaceId]/flows/{+page.svelte, CreateFlowDialog.svelte,
FlowsTable.svelte, FlowDraftsResumeStrip.svelte, ai-builder/, [flowId]/}. Deletion-first: the redesign replaces
FlowAIBuilderChat/Canvas/TaskPane/DraftsResumeStrip patterns — delete what the new structure makes redundant,
do not keep two patterns. Shared layout owner lib/components/layout/Page/* (header/tabbar) was just fixed
(6ec8a29d8) — do not restyle it. Backend contract: eneo.flows.ai_builder (router `/ai-builder`, event stream,
sessions, structured questions with `question_answer`, `requirements_confirmation` with `requirements_version`
and an EMPTY message on the confirmation turn (prose on that turn is a new user message that re-discloses),
requirements summary/disclosure with key decisions + assumptions + attested requirements, plan proposal
events, apply → flow; edits are step-scoped; model_ref is immutable from chat (a model-only request must get a
typed decline: "Jag kan inte byta modell åt dig — det gör du i stegredigeraren"; the typed decline outcome is
landing this evening on lane/edit-lane — build the UI against protocol.ts and coordinate). Read
frontend/packages/eneo-js (schema.d.ts is generated — never hand-edit; drift check pipeline regenerates it).
Also read docs/flows/*.md and .codex/artifacts/flow-builder-measure-20260816/tuesday-readiness/RECEIPT.md
§2 for the run contract (`steps_requiring_review`, `final_output.output_type`) that the plan screen must show
(review checkpoints "Granskning · du godkänner först", per-file steps, artifact outputs).

Standards: AGENTS.md; skills `impeccable` (+ `npx impeccable detect --json <paths>`) and
`ui-ux-frontend-analysis`; shadcn-svelte + Eneo tokens only (Svelte 5; svelte MCP validation); sv first,
natural Swedish for municipal first-time users, en second (not 1:1); accessible (focus, keyboard, aria-live);
responsive verified at 1280x800, 1440x900, 1512x982, 1920x1080, 2560x1440, 3440x1440 + 375 mobile — screenshots
in the report; Codex peer gate before every commit (skill /Users/ccimen/.claude/skills/codex-peer-loop/SKILL.md,
Bash run_in_background:true, `--artifact-dir /Users/ccimen/eneo/eneo-flows-clean/.codex/artifacts`,
`--require-green --required-min-score 8`, plan pass xhigh first for the slicing plan); tests proportional
(component tests for state logic; e2e for the happy path + re-confirm + change request); `bun run check`, lint,
i18n key parity; commit with SKIP=pyright if the pyright hook complains about the missing devcontainer.
Slice it (each its own gated commit, each viewable): (1) Flöden list + Skapa dialog + empty/search states;
(2) Ny uppgift + Frågor (all question shapes incl. file upload, multi-select, free text; 0–3 questions);
(3) Bekräfta incl. re-confirm state and attachments row; (4) Bygger (skeleton/slow/failure/cancel) + Granska
(diagram/detaljer, 12-step scale, review/per-file/artifact markers, change request pending→result, decline);
(5) approval outcome + Samtal sheet + conflict/unsaved states + mobile. Keep a live preview for the owner:
Vite dev server on http://127.0.0.1:3131 from your worktree against a running backend — the developz
devcontainer stack (DB developz_devcontainer-db-1) or a lane API started with the pattern in
/private/tmp/claude-501/-Users-ccimen-eneo-eneo-flows-clean/606c1cf8-e367-48c5-a92a-80b1f0dd43cb/scratchpad/measure-env.sh
(own container names, own port; never touch eneo-measure-* or eneo-lane-* containers). Login user@example.com /
Password1!. Night window: pause 01:00–06:00 Stockholm; no Codex launch after 00:10. Report per slice:
mapping table (design element → component), deviations with reasons, screenshots, gate score, sha, diff stat.
