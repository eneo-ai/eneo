# Granskning: `feature/personal-chat-governance-plan`

Kodgranskning av branchen mot `develop`. Fynd hittade via fan-out av review-agenter
(buggvinklar + reuse/simplification/efficiency/altitude) och därefter manuellt
verifierade mot koden. Konfidens: **verifierad** = bekräftad genom kodläsning,
**plausibel** = realistiskt men ej kört.

Status: `[ ]` = ej åtgärdad, `[x]` = åtgärdad, `[~]` = pågår.

> **Åtgärdat 2026-06-10:** fynd 1–7, 9, 11, 13, 14 fixade och verifierade
> (1954 backend unit-tester + governance/prompt_library-integrationstester gröna,
> pyright + svelte-check + eslint rena på ändrade filer, 5 nya backend-regressionstester).
> Kvar: 8, 10, 12 (plausibla) + cleanup 15–21. Detaljer per punkt nedan.

---

## 🔴 Allvarliga (auktorisering / kontrakt) — fixa före merge

- [x] **1. Preflight tappade behörighetskontroll → info-läcka** ·
  `backend/src/intric/conversations/application/conversation_service.py:249,254` (verifierad)
  Gamla `_resolve_preflight_model` anropade `assistant_service.get_assistant()` (kastar
  `UnauthorizedException`). Nya koden anropar `get_effective_completion_model()` som saknar
  all actor-kontroll (`assistant_service.py:789`). `_validate_conversation_scope` returnerar
  tidigt för vanliga inloggade användare (`scope_type in (None, "tenant")`). Följd: vilken
  autentiserad användare som helst kan `POST /conversations/preflight` med godtyckligt
  `assistant_id` (annans space/tenant) och få `model_name` + `context_window` istället för 403.

- [x] **2. `get_assistant_with_effective_config` tappade personal-default carve-out** ·
  `backend/src/intric/assistants/assistant_service.py:762` (verifierad, hittad av 3 agenter)
  `get_assistant()` har carve-out (rad 731–743): personliga default-assistenten gateas av
  `can_read_default_assistant()` (PERSONAL_CHAT), inte `can_read_assistants()` (ASSISTANTS).
  Nya `get_assistant_with_effective_config()` kollar bara `can_read_assistants()`. Både
  `GET /assistants/{id}/` och uppdaterings-endpointen (`assistant_router.py:247,717` →
  `_assistant_response`) går via den. Följd för PERSONAL_CHAT-only-användare (featurens
  målgrupp): modellväljaren PATCHar default-assistenten, service tillåter ändringen, men
  avslutande `_assistant_response` kastar 403 → UI visar fel trots sparad ändring. Ren GET
  regredierar 200→403.

- [x] **3. `PATCH /spaces/{id}/` tappar `effective_config`** ·
  `backend/src/intric/spaces/api/space_router.py:326` (verifierad, hittad av 3 agenter)
  `update_space` returnerar `assembler.from_space_to_model(space)` direkt istället för nya
  `_space_response()`. Personliga default-assistentens `effective_config` blir `None`. Bryter
  mot kontraktet (memory: `project_governance_effective_config_contract`).
  `from_space_to_sparse_model` (listan) och dashboard-modellen har samma lucka. Frontend
  `SpacesManager.updateSpace` sätter `currentSpace` från svaret → chat-UI tappar
  governance-filtrering tills nästa full GET. Latent men fel altitude — attachment hör hemma
  i assembler/service, inte per endpoint.

## 🟠 Funktionella buggar

- [x] **4. Otillgängliga-men-grantade MCP-servrar → tyst borttagna tool-denials** ·
  `frontend/apps/web/src/routes/(app)/admin/personal-assistant/configuration/policyDraft.svelte.ts:125,147,414`
  (verifierad, hittad av 2 agenter)
  `#allMcpServers` filtreras på `is_available` (nåbar nu) men backend validerar på `is_enabled`
  (admin-aktiverad) — olika fält (`governance_policy_service.py:141`). En enabled-men-onåbar
  server filtreras bort ur `#allMcpServers`, men `#seed` behåller den i `mcpSelections` och
  `#doSave` skickar den. `disabledToolIdsForSelectedServers(this.#allMcpServers, …)` filtrerar
  bort dess tool-denials → när servern kommer tillbaka är tidigare nekade verktyg tyst
  återaktiverade för alla. Dessutom: osynlig i UI (kan ej avmarkeras), `mcpSummary` kan visa
  "2 of 1".

- [x] **5. `partnerRuntimeSignature` hashar inte MCP/prompt-fält** ·
  `frontend/apps/web/src/lib/features/chat/ChatService.svelte.ts:850` (verifierad, hittad av 2 agenter)
  Signaturen tar bara `id/type/name/completion_model` + modell-fälten ur `effective_config`.
  MCP-fält (`mcp_enforced`, `available_mcp_servers`, `default_disabled_mcp_server_ids`) och
  prompt saknas. `changeChatPartner` early-returnar på matchande signatur → ändrar admin bara
  MCP-dimensionen behålls gammal partner: composern listar fel MCP-servrar tills
  modellbyte/omladdning. Backend enforcar fortfarande (inget säkerhetshål).

- [x] **6. `ChatModelSelect` kan krascha på dashboard-routen** ·
  `frontend/apps/web/src/lib/features/chat/components/conversation/ConversationInput.svelte:288`
  (plausibel)
  `ChatModelSelect` renderas när `chat.partner.type === "default-assistant"` och anropar
  `getSpacesManager()`, vars context bara sätts under `routes/(app)/spaces/+layout`.
  Deep-link `/dashboard/{defaultAssistantId}` ger partner-typ `default-assistant` →
  `getSpacesManager()` kastar vid mount → chat-sidan kraschar.

- [x] **7. Ordningskänslig modelljämförelse → falska audit-events** ·
  `backend/src/intric/governance_policy/presentation/governance_policy_router.py:25` (verifierad)
  `before_models`/`after_models` jämförs som osorterade listor medan `provider_ids`,
  `mcp_servers`, `disabled_mcp_tool_ids` normaliseras via `_ids`/`sorted`. Samma uppsättning i
  annan ordning loggar ett `GOVERNANCE_POLICY_UPDATED`-event med identiskt old/new. Fix: sortera.

- [ ] **8. `repo.save()` = lost update vid samtidiga admins** ·
  `backend/src/intric/governance_policy/infrastructure/governance_policy_repo_impl.py:106`
  (plausibel)
  `save()` raderar och skriver om alla fyra m2m-tabeller från in-memory-objektet utan
  version/lås. Admin A (bara modeller) + admin B (bara MCP, läst före A:s commit) → B skriver
  över A:s whitelist utan fel/audit. Behöver optimistisk versionskontroll.

- [x] **9. `prompt_library` check-then-insert race → 500** ·
  `backend/src/intric/prompt_library/application/prompt_library_service.py:65,93` (plausibel)
  `exists_by_name` + insert utan `IntegrityError`-hantering mot `uq_prompt_library_tenant_name`.
  Samtidiga creates med samma namn → 500 istället för 409. `mcp_server_service` fick
  `NameCollisionException`-catch i samma vända; den här missades.

- [ ] **10. `add_mcp_to_assistant` inkonsekvent med `update_assistant`** ·
  `backend/src/intric/assistants/assistant_service.py:1580` (plausibel)
  Dedikerade endpointen kör space-assignment-kontroll före governance och hård-failar, medan
  `update_assistant` hoppar över space-kontrollen när MCP-policyn styr. Policy-tillåten server
  som aktiverades efter space-seed: går via bulk-update men 400 via
  `POST /assistants/{id}/mcp-servers/{id}`.

## 🟡 Prestanda

- [x] **11. `effective_config_service` hämtar hela katalogen även med restriktioner avstängda** ·
  `backend/src/intric/governance_policy/application/effective_config_service.py:87` (verifierad)
  `resolve_for` hämtar alla completion-modeller + alla MCP-servrar (med tools), sekventiellt,
  så fort en policy-rad finns — utan att gate:a på `models_restriction_enabled`/
  `mcp_restriction_enabled`. `get_policy` auto-skapar tom policy när admin öppnar konfig-sidan.
  Därefter betalar varje ask/preflight/GET space/GET assistant i tenanten 2 extra
  full-table-hämtningar för noll beteendeändring. Gate på flaggorna + `asyncio.gather`.

- [ ] **12. `update_assistant` gör ~3 fulla space-loads per save** ·
  `backend/src/intric/assistants/api/assistant_router.py:717` (plausibel)
  Modellväljaren PATCHar vid varje byte; avslutande `_assistant_response` om-laddar hela
  space-aggregatet + ny effective_config-resolution fast `updated_assistant` finns i handen.

- [x] **13. `onReasoning` kringgår rAF-bufferten** ·
  `frontend/apps/web/src/lib/features/chat/ChatService.svelte.ts:549` (plausibel)
  `onText` batchar via `#streamBuffer` men reasoning-deltan appendas direkt till reaktiv state
  → re-render per reasoning-token under thinking-tunga modeller. Lägg i samma buffert.

## 🔵 Migration

- [x] **14. In-place-ändring av `down_revision` på committad migration** ·
  `backend/alembic/versions/202606091000_governance_policy_mcp_defaults_and_tools.py:19`
  (okommittad)
  Ändrar `down_revision` till tupel — gör om migrationen till merge-nod i efterhand. För DB som
  redan kört committade versionen blir `alembic_version` inkonsekvent. Blast-radius i praktiken
  egen dev-DB (branchen ej mergad), men rena sättet är `alembic merge` (ny revision).

## ⚪ Cleanup / altitude

- [ ] **15. Effektiv-modell-fallback finns i 3 kopior med olika ordning** — backend
  `policy_resolver.select_effective_completion_model`, `ChatService.#partnerEffectiveModel`
  (`available_models[0]`), `ChatModelSelect.selectedModel` (`sortModels()`-sorterad
  `visibleModels[0]`). Kan välja olika modell när policy saknar default. Extrahera en
  frontend-helper som speglar backend-resolvern.
- [ ] **16. `dev/chat-demo` + `dev/reasoning-preview` (~700 rader prototyp) skeppas som publika
  routes** under `(public)`, hårdkodad svenska + per-fil `eslint-disable`. UX:en finns redan som
  produktions-`ReasoningTrace`/`ReasoningToolStep`. Ta bort eller gate:a med
  `if (!import.meta.env.DEV) error(404)`.
- [ ] **17. Dubblerad tool-deny-pruning** — `toggleMcp` (eager) + `disabledToolIdsForSelectedServers`
  (save), olika traverseringar av samma källa. Välj en ägare.
- [ ] **18. Handrullad collapsible** i `ReasoningTrace`/`ReasoningToolStep` istället för bits-ui
  `$lib/components/ui/collapsible` → svagare a11y.
- [ ] **19. `MessageAnswer`**: sista trace-steget visar "Running…"-spinner medan ett annat
  verktyg väntar på godkännande — `!hasPendingApproval`-guarden tappades.
- [ ] **20. `prompt_library_router`** konstruerar `PaginatedResponse(items=…)` direkt; alla andra
  ~41 ställen använder `protocol.to_paginated_response()`.
- [ ] **21. `pre_push_check.py:199` / `commit_preflight.py:122`**: `contains_route_decorator(path)`
  läser working-tree-filen och returnerar `False` för raderade router-filer → borttagen router
  triggar inte route-metadata/schema-drift-kollen.

---

## Åtgärdslogg (2026-06-10)

- **1 & 2 – auth:** extraherade `_authorize_read_assistant(space, assistant)` i
  `assistant_service.py` med personal-default carve-outen (PERSONAL_CHAT vs ASSISTANTS).
  `get_assistant`, `get_assistant_with_effective_config` och `get_effective_completion_model`
  (preflight) anropar nu alla samma helper → ett enda enforcement-ställe. Regressionstester:
  `test_get_effective_completion_model_enforces_read_auth` +
  `_allows_personal_default_for_baseline_user`.
- **3 – effective_config-kontrakt:** `update_space` (PATCH) serialiserar nu via
  `_space_response()` istället för `from_space_to_model` direkt. (Kvar som uppföljning #15-altitude:
  flytta attachment till assembler/service så `from_space_to_sparse_model`/dashboard-modellen
  också täcks — separata endpoints kan fortfarande glömma helpern.)
- **4 – MCP-policy:** utredning visade att `is_available` är ett `computed_field` som returnerar
  `is_org_enabled`, och assemblern sätter `is_org_enabled = mcp_server.is_enabled` → frontend-filtret
  matchar exakt backend-valideringen. Verklig trigger är därför "server avaktiverad efter grant"
  (inte transient onåbarhet). Fix: `#selectableServerIds`/`#selectableToolIds` används i seed +
  baseline + (via befintlig helper) payload, så en orphaned grant varken bryter saven eller blåser
  upp summary-räknaren; den prunas ur policyn vid nästa MCP-save.
- **7 – audit:** `before_models`/`after_models` sorteras nu på id (`_model_entries`) som övriga dim.
- **11 – perf:** `resolve_for` gate:ar katalog-hämtningarna på `models_restriction_enabled`/
  `mcp_restriction_enabled` och kör modeller/MCP/prompt via `asyncio.gather`. Regressionstest:
  `test_resolve_for_all_restrictions_disabled_skips_catalog_fetches`.

**Verifiering:** 1952 backend unit-tester + 4 governance-integrationstester gröna, pyright 0 fel på
ändrade filer, `bun run check` (svelte-check) 0 fel. Frontend-vitest kunde ej köras i containern
(tinypool kräver node som saknas; körs i CI).

### Andra omgången (2026-06-10)

- **5 – stale partner:** `partnerRuntimeSignature` hashar nu även `mcp_enforced`,
  `available_mcp_server_ids`, `default_disabled_mcp_server_ids` och `prompt_locked` → en
  policyändring som bara rör MCP/prompt byter partner och composern uppdateras.
- **6 – dashboard-krasch:** `ConversationInput` hämtar `getSpacesManager()` och gate:ar
  `showModelSelect` på dess närvaro. Utan spaces-context (t.ex. deep-link i dashboard-chatten)
  monteras `ChatModelSelect` inte → ingen krasch på destrukturering av undefined.
- **9 – prompt_library race:** behåller pre-checken men fångar `IntegrityError` på
  `uq_prompt_library_tenant_name` i `create_entry`/`update_entry` och översätter till samma
  400 (`_name_collision_or_reraise`, re-raisar orelaterade integrity-fel). Tester:
  `test_create_translates_name_collision_integrity_error` + `_reraises_unrelated_integrity_error`.
- **13 – reasoning-jank:** reasoning-deltan buffras nu genom samma rAF-loop som svarstext
  (`#reasoningBuffer` + `#appendReasoning`, flushas i `#flushLoop`/`#finalizeStream`) i stället
  för att mutera reaktiv state per token.
- **14 – migration:** återställde in-place-redigeringen av `202606091000` och skapade i stället
  en dedikerad tom merge-revision `b3916fa5aac6` (`down_revision = (a1d4c7e90f23, 202606091000)`) —
  kanoniskt `alembic merge heads`, säkert för både färska DB:er och de som redan kört föregående
  version. `alembic heads` → en head. Verifierat via governance/prompt_library-integrationstester.

**Kvar (medvetet ej åtgärdade denna omgång):** 8 (optimistisk låsning — större ändring), 10
(MCP-attach-altitude), 12 (save-loads-perf), samt cleanup 15–21 (bl.a. ta bort dev/chat-demo,
dela fallback-helper, bits-ui collapsible). Notering: `frontend/apps/web/coverage/` är incheckad
genererad testoutput som triggar `intric/no-raw-color` i lint — bör gitignore:as (utanför denna
gransknings scope).
