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
/** @typedef {"reassigned" | "unassigned" | "reset_instructions_only" | "reset_to_default" | "archived"} AssignmentHistoryReason */
/** @typedef {"no_assignment" | "role_disabled" | "role_not_visible" | "no_completion_model" | "no_edit_rights"} HelperUnavailableReason */

/**
 * @typedef {Object} RoleAssignmentPublic
 * @property {string} id
 * @property {string} org_space_id
 * @property {HelperKind} kind
 * @property {string} assistant_id
 * @property {boolean} is_enabled
 * @property {boolean} is_visible_to_users
 * @property {string} created_at
 * @property {string} updated_at
 */

/**
 * @typedef {Object} AssignmentHistoryPublic
 * @property {string} id
 * @property {string} org_space_id
 * @property {HelperKind} kind
 * @property {string | null} assistant_id
 * @property {string} assistant_name_snapshot
 * @property {string | null} replaced_by_assistant_id
 * @property {AssignmentHistoryReason} reason
 * @property {string | null} actor_user_id
 * @property {string} replaced_at
 */

/**
 * @typedef {Object} AssistantSummaryPublic
 * @property {string} id
 * @property {string} name
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
       * Assign an existing assistant to a helper kind.
       * @param {{kind: HelperKind, assistant_id: string}} params
       * @returns {Promise<RoleAssignmentPublic>}
       * @throws {IntricError}
       */
      assign: async ({ kind, assistant_id }) => {
        // @ts-ignore - endpoint exists in backend but not yet in generated schema
        const res = await client.fetch("/api/v1/admin/help-assistants/roles/{kind}/assign", {
          method: "post",
          params: { path: { kind } },
          requestBody: { "application/json": { assistant_id } }
        });
        return /** @type {RoleAssignmentPublic} */ (res);
      },

      /**
       * Unassign the active role for a helper kind. Returns `true` on success.
       * @param {{kind: HelperKind}} params
       * @returns {Promise<true>}
       * @throws {IntricError}
       */
      unassign: async ({ kind }) => {
        // @ts-ignore - endpoint exists in backend but not yet in generated schema
        await client.fetch("/api/v1/admin/help-assistants/roles/{kind}/", {
          method: "delete",
          params: { path: { kind } }
        });
        return true;
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
       * Reset the active helper's instructions to the registry default while
       * keeping the same assistant id (instructions-only reset, PRD §6).
       * @param {{kind: HelperKind}} params
       * @returns {Promise<true>}
       * @throws {IntricError}
       */
      resetInstructions: async ({ kind }) => {
        // @ts-ignore - endpoint exists in backend but not yet in generated schema
        await client.fetch("/api/v1/admin/help-assistants/roles/{kind}/reset-instructions", {
          method: "post",
          params: { path: { kind } }
        });
        return true;
      },

      /**
       * Full reset: archive the current helper and create a fresh one from the
       * defaults registry (PRD §6).
       * @param {{kind: HelperKind}} params
       * @returns {Promise<true>}
       * @throws {IntricError}
       */
      resetToDefault: async ({ kind }) => {
        // @ts-ignore - endpoint exists in backend but not yet in generated schema
        await client.fetch("/api/v1/admin/help-assistants/roles/{kind}/reset-to-default", {
          method: "post",
          params: { path: { kind } }
        });
        return true;
      },

      /**
       * List the assignment history for a helper kind (replacements, resets,
       * archives), newest first.
       * @param {{kind: HelperKind}} params
       * @returns {Promise<AssignmentHistoryPublic[]>}
       * @throws {IntricError}
       */
      listHistory: async ({ kind }) => {
        // @ts-ignore - endpoint exists in backend but not yet in generated schema
        const res = await client.fetch("/api/v1/admin/help-assistants/roles/{kind}/history", {
          method: "get",
          params: { path: { kind } }
        });
        return /** @type {{items: AssignmentHistoryPublic[]}} */ (res).items;
      },

      /**
       * List replaced helper assistants for a kind that can still be archived
       * (PRD §6 — admins can hard-archive helpers that are no longer active).
       * @param {{kind: HelperKind}} params
       * @returns {Promise<AssistantSummaryPublic[]>}
       * @throws {IntricError}
       */
      listArchivable: async ({ kind }) => {
        // @ts-ignore - endpoint exists in backend but not yet in generated schema
        const res = await client.fetch("/api/v1/admin/help-assistants/roles/{kind}/archivable", {
          method: "get",
          params: { path: { kind } }
        });
        return /** @type {{items: AssistantSummaryPublic[]}} */ (res).items;
      },

      /**
       * Archive a replaced helper assistant. The kind is part of the URL for
       * symmetry with the other admin routes; only the assistant id drives the
       * action server-side.
       * @param {{kind: HelperKind, assistant_id: string}} params
       * @returns {Promise<true>}
       * @throws {IntricError}
       */
      archive: async ({ kind, assistant_id }) => {
        await client.fetch(
          // @ts-ignore - endpoint exists in backend but not yet in generated schema
          "/api/v1/admin/help-assistants/roles/{kind}/archive/{assistant_id}",
          {
            method: "post",
            params: { path: { kind, assistant_id } }
          }
        );
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
