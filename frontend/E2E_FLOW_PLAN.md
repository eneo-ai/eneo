# Frontend E2E flow plan

## Purpose

The E2E suite should prove that important backend capabilities are consumed
correctly through the frontend and other supported consumers.

An E2E flow is valuable when it verifies the complete contract:

1. The UI sends the intended command.
2. The backend accepts or rejects it according to domain rules and permissions.
3. The resulting state is persisted.
4. The frontend renders that state correctly after a reload or in a new session.
5. A user or API consumer can use the result as intended.

The suite should not repeat every backend validation or component rendering
variant. Those remain cheaper and easier to diagnose in backend, unit, and
component tests.

## Current baseline

The mandatory Playwright suite currently covers:

- successful and rejected username/password login;
- redirect from protected routes;
- authenticated landing and primary navigation;
- account information;
- logout and session invalidation;
- sending a deterministic chat message;
- streaming and persisting the answer;
- reopening the conversation from history and after a reload.

This gives us a useful smoke test, but it does not yet prove the main authoring,
permission, publishing, administration, or asynchronous processing workflows.
Backend tests cover much of their domain logic in isolation; the E2E gaps are
primarily in the contracts between UI state, API payloads, permissions, persisted
state, and consumer-facing results.

## Test selection rules

Add an E2E flow when at least one of these is true:

- a failure would block a core user journey;
- the flow crosses several boundaries, such as UI, API, database, worker, or
  websocket/SSE;
- permissions change both the available UI and the backend outcome;
- frontend form state is translated into a complex backend command;
- an authored resource is later consumed from another page, session, role, or
  API client;
- the frontend has meaningful recovery behavior for a backend or streaming
  failure.

Do not add an E2E test only to cover:

- every field validation or visual variant;
- pure formatting or transformation logic;
- every backend permission combination;
- implementation details that are already covered by a smaller test;
- third-party availability in the pull-request suite.

For each major workflow, prefer one representative success journey and one
high-risk permission or failure journey.

## Mandatory pull-request suite

These flows should be deterministic, isolated from external services, and remain
part of the blocking `Frontend E2E` CI job.

### 1. Authentication and session lifecycle

**Status:** covered.

**Journey**

1. An anonymous user is redirected from a protected route.
2. Invalid credentials produce an accessible error without creating a session.
3. Valid credentials create a session and open the application.
4. Logout invalidates the session and protects previously accessible routes.

**Contract proved:** browser cookies, frontend guards, authentication API, error
presentation, and session invalidation agree.

### 2. Personal chat lifecycle

**Status:** covered.

**Journey**

1. The user sends a message through the editor.
2. The answer is streamed from the deterministic model service.
3. Both messages are rendered and persisted.
4. The conversation can be reopened from history.
5. The same state remains after a full reload.

**Contract proved:** chat input, conversation API, SSE streaming, persistence, and
history rendering work together.

### 3. Assistant authoring to consumption

**Priority:** next.

**Journey**

1. Create an assistant from the UI with a unique name.
2. Configure its prompt and completion model.
3. Save it and reload the edit page.
4. Verify that the persisted configuration is shown.
5. Publish it.
6. Open it from the dashboard and send a message.
7. Verify the deterministic answer and persisted conversation.
8. Unpublish it and verify that it is no longer offered as a published resource.

**Contract proved:** editor form state, assistant API payloads, persistence,
publishing, dashboard discovery, and runtime chat use the same resource
correctly.

**Avoid:** asserting every editor control. Detailed editor behavior belongs in
component tests.

### 4. Shared space and permission enforcement

**Priority:** next.

**Journey**

1. An owner creates a restricted role, a user, and a shared space.
2. The owner adds the user to the space with that role.
3. The restricted user signs in using a separate browser context.
4. The user can discover and use the allowed shared resource.
5. Edit, publish, member-management, and other denied actions are absent.
6. Direct navigation or an API request for a denied action is also rejected.
7. A permitted change made by the owner becomes visible to the restricted user.

**Contract proved:** role configuration, space membership, frontend capability
rendering, backend authorization, and cross-session state agree.

Use one representative restricted role. The backend suite should continue to
cover the full permission matrix.

### 5. API key from administration to real consumer

**Priority:** next.

**Journey**

1. An owner creates a scoped API key through the admin UI.
2. The one-time secret is shown and captured.
3. Playwright's request client uses the secret against a stable endpoint allowed
   by the selected scope.
4. The response proves that the key is usable by an actual API consumer.
5. The owner revokes the key in the UI.
6. Repeating the same request is rejected.
7. The UI shows the revoked state after a reload.

**Contract proved:** admin form payload, secret presentation, authentication
middleware, scope enforcement, revocation, and persisted status.

This gives broader value than duplicating the backend's extensive API-key unit
and integration test matrix.

### 6. Model or stream failure recovery

**Priority:** next.

**Journey**

1. Send a marker message that makes the local model mock return a deterministic
   HTTP or stream error.
2. Verify that the frontend presents an understandable error.
3. Verify that no successful assistant answer is falsely persisted.
4. Confirm that the user's input or conversation remains recoverable.
5. Retry with a successful marker and verify that the conversation can continue.

**Contract proved:** backend error translation, SSE termination, frontend state
cleanup, persistence, and retry behavior.

This requires extending the model mock with request-controlled success and error
responses.

## Mandatory after test infrastructure expansion

These are core flows, but should only become blocking after their local
dependencies are deterministic and stable.

### 7. App authoring and asynchronous run

**Journey**

1. Create and configure an app in the UI.
2. Save, reload, and publish it.
3. Run it from the dashboard with known input.
4. Observe the queued/running state.
5. Receive the websocket update and open the completed result.
6. Reload and verify that the result remains available.

**Infrastructure required**

- an ARQ worker in the E2E Docker Compose stack;
- seeded completion and transcription model capabilities;
- deterministic local model responses.

**Contract proved:** app editor, publishing, job queue, worker, websocket updates,
result persistence, and dashboard rendering.

### 8. Knowledge upload to grounded answer

**Journey**

1. Create a collection.
2. Upload a small document containing a unique known fact.
3. Wait for indexing to complete and verify the document state.
4. Attach the collection to an assistant.
5. Ask a question whose answer exists only in that document.
6. Verify the expected grounded answer and its source/reference.
7. Reload the conversation and verify that the answer remains.

**Infrastructure required**

- an ARQ worker;
- a deterministic local embeddings endpoint and seeded embedding model;
- a small fixture document;
- deterministic model behavior that can respond from the supplied context.

**Contract proved:** upload, background processing, embeddings, collection
selection, assistant configuration, retrieval, generation, citations, and
frontend presentation.

This is the strongest whole-product E2E candidate and should become mandatory
once it is reliable.

### 9. Auditable administration action

Extend one existing mutation flow rather than creating a broad audit-log test:

1. Perform a distinctive action such as publishing an assistant, creating an API
   key, or changing a user.
2. Open the audit log.
3. Verify the action, actor, target, and timestamp are presented correctly.

**Contract proved:** domain event creation, audit persistence, API serialization,
label mapping, and admin rendering.

## Nightly or provider-contract suite

Keep these out of the blocking pull-request path until they use reliable local
provider mocks:

- OIDC/federation login and callback failures using a mock identity provider;
- website crawling against a local fixture site;
- SharePoint and other integration authorization/synchronization;
- SCIM provisioning;
- multi-tenant isolation journeys;
- provider-specific completion, transcription, or embedding contracts;
- browser and mobile-layout coverage beyond the primary Chromium desktop path.

These tests are still valuable, but external availability and provider behavior
must not make ordinary pull requests flaky.

## Implementation order

### Phase 1: Strengthen the current blocking suite

1. Assistant authoring to consumption.
2. Shared-space permission enforcement.
3. API-key consumer lifecycle.
4. Model/stream failure recovery.

Keep these flows independent and use unique resource names. Use API or seed
helpers for prerequisite data when setup itself is not the behavior being tested.

### Phase 2: Add deterministic asynchronous infrastructure

1. Add the worker service to local and CI E2E Compose files.
2. Seed all model capabilities required by apps and knowledge.
3. Extend the mock model service with completion, error, transcription, and
   embedding behavior as needed.
4. Add app execution and knowledge-to-answer flows.
5. Make the new flows blocking only after repeated stable CI runs.

### Phase 3: Expand consumer and provider confidence

1. Add the audit assertion to an existing administration journey.
2. Add mock-provider flows for OIDC, crawling, and integrations.
3. Run provider-heavy and broader browser coverage on a nightly schedule.

## Test design and CI guardrails

- Use the UI for the behavior under test; use seed/API helpers for unrelated
  setup and cleanup.
- Give each test its own data and never rely on test order.
- Prefer role, label, and semantic locators over CSS structure or translated
  display text.
- Assert durable outcomes after reload, a new page, or a second browser context.
- Assert backend denial as well as hidden controls for permission tests.
- Keep third-party network access disabled in the mandatory suite.
- Capture Playwright traces, screenshots, and the HTML report on failure.
- Retry only in CI and investigate repeated first-attempt failures as flakes.
- Keep the mandatory browser journeys few enough to remain understandable and
  fast; add lower-level tests when a flow starts branching into many variants.

## Definition of done for a new mandatory flow

A flow is ready to block pull requests when:

- it runs against the isolated E2E stack with no production credentials;
- all external responses are deterministic;
- it owns its test data and passes when run alone;
- it verifies a persisted or cross-consumer outcome, not only a toast;
- it has failed for an intentional product regression during development;
- failure artifacts make the broken boundary diagnosable;
- repeated CI runs show no unexplained retries or timing dependence.
