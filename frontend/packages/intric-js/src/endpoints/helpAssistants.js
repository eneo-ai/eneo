/** @typedef {import('../client/client').IntricError} IntricError */

/**
 * Help-assistants client surface (PRD §5, §10).
 *
 * Two grouped objects:
 * - `admin`: tenant-admin role management under `/api/v1/admin/help-assistants/...`
 * - `runs`: per-user helper-run invocation under `/api/v1/help-assistants/...`
 *
 * The backend OpenAPI schema has not been regenerated yet, so every
 * `client.fetch` / `client.stream` call below uses `@ts-ignore` (matching
 * the precedent set by `assistants.listPrompts`). Return shapes are
 * documented via JSDoc typedefs at the top of this file; when the schema is
 * next regenerated (via `node update.js`) these typedefs can be replaced
 * with `components["schemas"]["..."]` aliases in `types/resources.d.ts`.
 */

/** @typedef {"prompt_guide"} HelperKind */
/** @typedef {"in_progress" | "completed" | "abandoned" | "failed"} HelperRunStatus */
/** @typedef {"no_assignment" | "role_disabled" | "role_not_visible" | "no_completion_model" | "no_edit_rights"} HelperUnavailableReason */

/**
 * @typedef {Object} RoleAssignmentPublic
 * @property {string} id
 * @property {string} org_space_id
 * @property {HelperKind} kind
 * @property {string} assistant_id
 * @property {string | null} [assistant_name] Display name of the assigned assistant. Resolved only on the read endpoints (`listRoles` / `getRole`); mutation responses leave it null since the admin UI re-fetches the list.
 * @property {boolean} is_enabled
 * @property {boolean} is_visible_to_users
 * @property {string} created_at
 * @property {string} updated_at
 */

/**
 * @typedef {Object} HelperTemplatePublic
 * @property {HelperKind} kind
 * @property {string} name
 * @property {string} description
 */

/**
 * @typedef {Object} HelperRunPublic
 * @property {string} id
 * @property {HelperKind} kind
 * @property {string | null} assistant_id
 * @property {string} target_type
 * @property {string} target_id
 * @property {string} session_id
 * @property {string | null} actor_user_id
 * @property {HelperRunStatus} status
 * @property {string | null} completed_at
 * @property {string | null} created_at
 * @property {string | null} updated_at
 */

/**
 * @typedef {Object} HelperRunReference
 * @property {string} id
 * @property {string | null} [title]
 * @property {string | null} [url]
 * @property {number} [score]
 */

/**
 * @typedef {Object} HelperRunResponsePublic
 * @property {HelperRunPublic} run
 * @property {string} answer
 * @property {HelperRunReference[]} references
 * @property {string | null} [error] Set on a terminal stream event when the completion provider fails mid-stream.
 */

/**
 * @typedef {Object} AvailabilityResponse
 * @property {boolean} available
 * @property {HelperUnavailableReason | null} [disabled_reason]
 */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initHelpAssistants(client) {
  return {
    admin: {
      /**
       * List the active role assignments for the caller's tenant org-space.
       * Returns one row per helper kind currently assigned.
       * @returns {Promise<RoleAssignmentPublic[]>}
       * @throws {IntricError}
       */
      listRoles: async () => {
        // @ts-ignore - endpoint exists in backend but not yet in generated schema
        const res = await client.fetch("/api/v1/admin/help-assistants/roles/", {
          method: "get"
        });
        return /** @type {{items: RoleAssignmentPublic[]}} */ (res).items;
      },

      /**
       * Get the active role for a specific helper kind. Returns `null` when no
       * assignment exists.
       * @param {{kind: HelperKind}} params
       * @returns {Promise<RoleAssignmentPublic | null>}
       * @throws {IntricError}
       */
      getRole: async ({ kind }) => {
        // @ts-ignore - endpoint exists in backend but not yet in generated schema
        const res = await client.fetch("/api/v1/admin/help-assistants/roles/{kind}/", {
          method: "get",
          params: { path: { kind } }
        });
        return /** @type {RoleAssignmentPublic | null} */ (res);
      },

      /**
       * Toggle `is_enabled` on the active role.
       * @param {{kind: HelperKind, value: boolean}} params
       * @returns {Promise<RoleAssignmentPublic>}
       * @throws {IntricError}
       */
      setEnabled: async ({ kind, value }) => {
        // @ts-ignore - endpoint exists in backend but not yet in generated schema
        const res = await client.fetch("/api/v1/admin/help-assistants/roles/{kind}/enabled", {
          method: "patch",
          params: { path: { kind } },
          requestBody: { "application/json": { value } }
        });
        return /** @type {RoleAssignmentPublic} */ (res);
      },

      /**
       * Toggle `is_visible_to_users` on the active role.
       * @param {{kind: HelperKind, value: boolean}} params
       * @returns {Promise<RoleAssignmentPublic>}
       * @throws {IntricError}
       */
      setVisible: async ({ kind, value }) => {
        // @ts-ignore - endpoint exists in backend but not yet in generated schema
        const res = await client.fetch("/api/v1/admin/help-assistants/roles/{kind}/visible", {
          method: "patch",
          params: { path: { kind } },
          requestBody: { "application/json": { value } }
        });
        return /** @type {RoleAssignmentPublic} */ (res);
      },

      /**
       * List shipped Help Assistant templates not yet installed for the
       * tenant. Drives the admin "Add help assistant" picker — a template
       * drops out once installed and reappears after it is uninstalled.
       * @returns {Promise<HelperTemplatePublic[]>}
       * @throws {IntricError}
       */
      listTemplates: async () => {
        // @ts-ignore - endpoint exists in backend but not yet in generated schema
        const res = await client.fetch("/api/v1/admin/help-assistants/templates/", {
          method: "get"
        });
        return /** @type {{items: HelperTemplatePublic[]}} */ (res).items;
      },

      /**
       * Install a shipped template: creates a blank helper assistant + active
       * role for `kind`. The helper starts enabled but not visible to users,
       * so an admin can paste the instructions before exposing it.
       * @param {{kind: HelperKind}} params
       * @returns {Promise<RoleAssignmentPublic>}
       * @throws {IntricError}
       */
      install: async ({ kind }) => {
        // @ts-ignore - endpoint exists in backend but not yet in generated schema
        const res = await client.fetch("/api/v1/admin/help-assistants/roles/{kind}/", {
          method: "post",
          params: { path: { kind } }
        });
        return /** @type {RoleAssignmentPublic} */ (res);
      },

      /**
       * Uninstall the active helper for `kind`: removes the role and
       * hard-deletes the underlying assistant. The template becomes available
       * to add again afterwards.
       * @param {{kind: HelperKind}} params
       * @returns {Promise<true>}
       * @throws {IntricError}
       */
      uninstall: async ({ kind }) => {
        // @ts-ignore - endpoint exists in backend but not yet in generated schema
        await client.fetch("/api/v1/admin/help-assistants/roles/{kind}/", {
          method: "delete",
          params: { path: { kind } }
        });
        return true;
      }
    },

    runs: {
      /**
       * Start a new helper run for `{kind, target_type, target_id, question}`.
       * The helper assistant is resolved server-side from the active role for
       * the caller's tenant (PRD §10) — the frontend never sends a helper
       * assistant id.
       *
       * When `stream` is true (default) the answer is streamed over SSE and
       * `onAnswer` is invoked for every chunk; the final accumulated response
       * is returned. When `stream` is false the response is a single JSON
       * payload and `onAnswer` / `onOpen` / `abortController` are ignored.
       *
       * @param {Object} params
       * @param {HelperKind} params.kind
       * @param {string} params.target_type Always `"assistant"` today; kept open for future targets.
       * @param {string} params.target_id Target resource id (the assistant being edited).
       * @param {string} params.question
       * @param {boolean} [params.stream] Stream the answer over SSE. Defaults to `true`.
       * @param {(partial: HelperRunResponsePublic, controller: AbortController) => void} [params.onAnswer] Called for each SSE chunk.
       * @param {(response: Response) => Promise<void>} [params.onOpen] Called once when the SSE response opens.
       * @param {AbortController} [params.abortController] Optional controller to abort the stream.
       * @returns {Promise<HelperRunResponsePublic>}
       * @throws {IntricError}
       */
      start: async ({
        kind,
        target_type,
        target_id,
        question,
        stream = true,
        onAnswer,
        onOpen,
        abortController
      }) => {
        if (!stream) {
          // @ts-ignore - endpoint exists in backend but not yet in generated schema
          const res = await client.fetch("/api/v1/help-assistants/runs/", {
            method: "post",
            requestBody: {
              "application/json": { kind, target_type, target_id, question, stream: false }
            }
          });
          return /** @type {HelperRunResponsePublic} */ (res);
        }

        let answer = "";
        let streamError = /** @type {string | null} */ (null);
        let response = /** @type {HelperRunResponsePublic} */ ({});

        await client.stream(
          // @ts-ignore - endpoint exists in backend but not yet in generated schema
          "/api/v1/help-assistants/runs/",
          {
            requestBody: {
              "application/json": { kind, target_type, target_id, question, stream: true }
            }
          },
          {
            onOpen: async (raw) => {
              if (onOpen) await onOpen(raw);
            },
            onMessage: (ev, controller) => {
              if (ev.data == "") return;
              try {
                const data = /** @type {HelperRunResponsePublic} */ (JSON.parse(ev.data));
                response = data;
                if (data.error) {
                  // Backend emits a terminal error event on mid-stream
                  // provider failure; capture it and throw after the stream
                  // so the caller's catch surfaces it (not a silent partial).
                  streamError = data.error;
                  return;
                }
                if (data.answer) {
                  answer += data.answer;
                  if (onAnswer) onAnswer(data, controller);
                }
              } catch {
                return;
              }
            }
          },
          abortController
        );

        if (streamError) throw new Error(streamError);
        response.answer = answer;
        return response;
      },

      /**
       * Follow-up turn on an existing helper run. Only the original actor may
       * follow up (the backend enforces this).
       *
       * @param {Object} params
       * @param {string} params.run_id
       * @param {string} params.question
       * @param {boolean} [params.stream] Stream the answer over SSE. Defaults to `true`.
       * @param {(partial: HelperRunResponsePublic, controller: AbortController) => void} [params.onAnswer]
       * @param {(response: Response) => Promise<void>} [params.onOpen]
       * @param {AbortController} [params.abortController]
       * @returns {Promise<HelperRunResponsePublic>}
       * @throws {IntricError}
       */
      continueTurn: async ({
        run_id,
        question,
        stream = true,
        onAnswer,
        onOpen,
        abortController
      }) => {
        if (!stream) {
          // @ts-ignore - endpoint exists in backend but not yet in generated schema
          const res = await client.fetch("/api/v1/help-assistants/runs/{run_id}/turns/", {
            method: "post",
            params: { path: { run_id } },
            requestBody: { "application/json": { question, stream: false } }
          });
          return /** @type {HelperRunResponsePublic} */ (res);
        }

        let answer = "";
        let streamError = /** @type {string | null} */ (null);
        let response = /** @type {HelperRunResponsePublic} */ ({});

        await client.stream(
          // @ts-ignore - endpoint exists in backend but not yet in generated schema
          "/api/v1/help-assistants/runs/{run_id}/turns/",
          {
            params: { path: { run_id } },
            requestBody: { "application/json": { question, stream: true } }
          },
          {
            onOpen: async (raw) => {
              if (onOpen) await onOpen(raw);
            },
            onMessage: (ev, controller) => {
              if (ev.data == "") return;
              try {
                const data = /** @type {HelperRunResponsePublic} */ (JSON.parse(ev.data));
                response = data;
                if (data.error) {
                  // Backend emits a terminal error event on mid-stream
                  // provider failure; capture it and throw after the stream
                  // so the caller's catch surfaces it (not a silent partial).
                  streamError = data.error;
                  return;
                }
                if (data.answer) {
                  answer += data.answer;
                  if (onAnswer) onAnswer(data, controller);
                }
              } catch {
                return;
              }
            }
          },
          abortController
        );

        if (streamError) throw new Error(streamError);
        response.answer = answer;
        return response;
      },

      /**
       * Transition a helper run to a terminal status. UX-driven: `completed`
       * from Apply, `abandoned` from closing the modal, `failed` from a
       * client-side fault. The backend rejects `in_progress` and rejects
       * repeat transitions on an already-terminal run.
       *
       * @param {{run_id: string, status: HelperRunStatus}} params
       * @returns {Promise<HelperRunPublic>}
       * @throws {IntricError}
       */
      setStatus: async ({ run_id, status }) => {
        // @ts-ignore - endpoint exists in backend but not yet in generated schema
        const res = await client.fetch("/api/v1/help-assistants/runs/{run_id}/", {
          method: "patch",
          params: { path: { run_id } },
          requestBody: { "application/json": { status } }
        });
        return /** @type {HelperRunPublic} */ (res);
      },

      /**
       * Cheap pre-flight before rendering the prompt-guide toolbar button.
       * Returns `{ available: true }` only when every backend gate passes
       * (role assigned + enabled + visible + completion model usable +
       * caller has EDIT on `target_id`).
       *
       * @param {{kind: HelperKind, target_id: string}} params
       * @returns {Promise<AvailabilityResponse>}
       * @throws {IntricError}
       */
      availability: async ({ kind, target_id }) => {
        // @ts-ignore - endpoint exists in backend but not yet in generated schema
        const res = await client.fetch("/api/v1/help-assistants/availability", {
          method: "get",
          params: { query: { kind, target_id } }
        });
        return /** @type {AvailabilityResponse} */ (res);
      }
    }
  };
}
