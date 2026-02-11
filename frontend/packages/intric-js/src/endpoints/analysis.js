/** @typedef {import('../types/resources').AnalyticsData} AnalyticsData */
/** @typedef {import('../types/resources').AnalyticsAggregatedData} AnalyticsAggregatedData */
/** @typedef {import('../types/resources').Assistant} Assistant */
import { IntricError } from "../client/client";

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initAnalytics(client) {
  return {
    /**
     * Get counts of assistants, sessions and questions.
     * @param {{start?: string, end?: string}} [params] Define start and end date for data; Expects UTC time string.
     * @returns {Promise<AnalyticsData>} The requested data
     * @throws {IntricError}
     * */
    get: async ({ start, end } = { start: undefined, end: undefined }) => {
      const res = await client.fetch("/api/v1/analysis/metadata-statistics/", {
        method: "get",
        params: { query: { start_date: start, end_date: end } }
      });
      return res;
    },

    /**
     * Get aggregated counts of assistants, sessions and questions.
     * @param {{start?: string, end?: string}} [params] Define start and end date for data; Expects UTC time string.
     * @returns {Promise<AnalyticsAggregatedData>} The requested data
     * @throws {IntricError}
     * */
    getAggregated: async ({ start, end } = { start: undefined, end: undefined }) => {
      const res = await client.fetch("/api/v1/analysis/metadata-statistics/aggregated/", {
        method: "get",
        params: { query: { start_date: start, end_date: end } }
      });
      return res;
    },

    /**
     * Get total current counts of assistants, sessions and questions.
     * @returns Counts
     * @throws {IntricError}
     * */
    counts: async () => {
      const res = await client.fetch("/api/v1/analysis/counts/", { method: "get" });
      return res;
    },

    /**
     * Get assistant activity statistics for the tenant.
     * @param {{start?: string, end?: string}} [params] Define start and end date for data; Expects UTC time string.
     * @returns {Promise<{active_assistant_count: number, total_trackable_assistants: number, active_assistant_pct: number, active_user_count: number}>} Activity stats
     * @throws {IntricError}
     * */
    getAssistantActivity: async ({ start, end } = { start: undefined, end: undefined }) => {
      const res = await client.fetch("/api/v1/analysis/assistant-activity/", {
        method: "get",
        params: { query: { start_date: start, end_date: end } }
      });
      return res;
    },

    /**
     * List all questions of an assistant in a specific period.
     * @param {Object} params
     * @param {{id: string} | Assistant} params.assistant
     * @param {{ start?: string, end?: string, includeFollowups?: boolean } | undefined} params.options Optionally provide start and end date in iso format (YYYY-MM-DD). Include followups defaults to false.
     * @throws {IntricError}
     * */
    listQuestions: async ({ assistant, options }) => {
      const include_followups = options?.includeFollowups ?? false;
      const { id } = assistant;
      const res = await client.fetch("/api/v1/analysis/assistants/{assistant_id}/", {
        method: "get",
        params: {
          path: { assistant_id: id },
          query: {
            from_date: options?.start,
            to_date: options?.end,
            include_followups
          }
        }
      });
      return res.items;
    },

    /**
     * List questions of an assistant in a specific period (cursor-paginated).
     * @param {Object} params
     * @param {{id: string} | Assistant} params.assistant
     * @param {{ start?: string, end?: string, includeFollowups?: boolean, limit?: number, cursor?: string, query?: string } | undefined} params.options
     * @throws {IntricError}
     * */
    listQuestionsPaginated: async ({ assistant, options }) => {
      const include_followups = options?.includeFollowups ?? false;
      const { id } = assistant;
      const endpoint =
        /** @type {any} */ ("/api/v1/analysis/assistants/{assistant_id}/questions/");
      const res = await client.fetch(endpoint, {
        method: "get",
        params: {
          path: { assistant_id: id },
          query: {
            from_date: options?.start,
            to_date: options?.end,
            include_followups,
            limit: options?.limit,
            cursor: options?.cursor,
            q: options?.query
          }
        }
      });
      return res;
    },

    /**
     * Ask an assistant a question. By default the answer is streamed from the backend, you can act on partial answer updates
     * with the onChunk callback. Once the answer has been fully received a complete `Session` object will be returned.
     * @param {Object} params Ask parameters
     * @param  {{id: string} | Assistant} params.assistant Which assistant to ask
     * @param {{ start?: string, end?: string, includeFollowups?: boolean } | undefined} params.options Optionally provide start and end date in iso format (YYYY-MM-DD). Include followups defaults to false.
     * @param {string} params.question Question to ask
     * @param {(token: string) => void} [params.onAnswer] Callback to run when a new token/word of the answer is received
     * @param {(response: Response) => Promise<void>} [params.onOpen] Callback to run once the initial response of the backend is received
     * @returns {Promise<{answer: string}>} Once the full answer is received it will be returned
     * @throws {IntricError}
     * */
    ask: async ({ assistant, options, question, onAnswer, onOpen }) => {
      const { id: assistant_id } = assistant;

      let answer = "";

      await client.stream(
        "/api/v1/analysis/assistants/{assistant_id}/",
        {
          params: {
            path: { assistant_id },
            query: {
              from_date: options?.start,
              to_date: options?.end,
              include_followups: options?.includeFollowups
            }
          },
          requestBody: { "application/json": { question, stream: true } }
        },
        {
          onOpen: async (response) => {
            if (onOpen) onOpen(response);
          },
          onMessage: (ev) => {
            if (ev.data == "") return;
            try {
              const data = JSON.parse(ev.data);
              if (data.answer) {
                answer += data.answer;
                if (onAnswer) onAnswer(data.answer);
              }
            } catch (e) {
              return;
            }
          }
        }
      );

      return { answer };
    },

    insights: {
      /**
       * Get insights for a specifc assistant or group chat
       * @param {Object} args
       * @param {import('./conversations').ChatPartner} args.chatPartner
       * @param {string} [args.startDate] Define start and end date for data; Expects UTC time string.
       * @param {string} [args.endDate] Define start and end date for data; Expects UTC time string.
       * @throws {IntricError}
       *
       */
      statistics: async ({ chatPartner, startDate, endDate }) => {
        /**  @type {{assistant_id?: string, group_chat_id?: string}} */
        const target = { assistant_id: undefined, group_chat_id: undefined };

        if (chatPartner.type === "assistant" || chatPartner.type === "default-assistant") {
          target.assistant_id = chatPartner.id;
        } else if (chatPartner.type === "group-chat") {
          target.group_chat_id = chatPartner.id;
        } else {
          throw new IntricError(
            "Asking a question requires one of 'assistant' or 'groupChat' to be specified",
            "CONNECTION",
            0,
            0
          );
        }

        const res = await client.fetch("/api/v1/analysis/conversation-insights/", {
          method: "get",
          params: {
            query: { ...target, start_time: startDate, end_time: endDate }
          }
        });

        return res;
      },

      conversations: {
        /**
         * Get a list of conversations that have happend in the specified timeframe
         * @param {Object} args
         * @param {import('./conversations').ChatPartner} args.chatPartner
         * @param {string} [args.startDate] Define start and end date for data; Expects UTC time string.
         * @param {string} [args.endDate] Define start and end date for data; Expects UTC time string.
         * @param {string} [args.nextCursor] Where to start getting conversations
         * @param {number} [args.limit] How many conversations to load
         * @param {string} [args.nameFilter] Optional server-side name filter
         * @throws {IntricError}
         *
         */
        list: async ({ chatPartner, startDate, endDate, nextCursor, limit, nameFilter }) => {
          /**  @type {{assistant_id?: string, group_chat_id?: string}} */
          const target = { assistant_id: undefined, group_chat_id: undefined };

          if (chatPartner.type === "assistant" || chatPartner.type === "default-assistant") {
            target.assistant_id = chatPartner.id;
          } else if (chatPartner.type === "group-chat") {
            target.group_chat_id = chatPartner.id;
          } else {
            throw new IntricError(
              "Asking a question requires one of 'assistant' or 'groupChat' to be specified",
              "CONNECTION",
              0,
              0
            );
          }

          const res = await client.fetch("/api/v1/analysis/conversation-insights/sessions/", {
            method: "get",
            params: {
              query: {
                ...target,
                start_date: startDate,
                end_date: endDate,
                cursor: nextCursor,
                limit,
                name_filter: nameFilter
              }
            }
          });

          return res;
        },

        /**
         *  Get a specific conversation by id
         * @param {{id: string}} conversation
         */
        get: async ({ id }) => {
          const res = await client.fetch(
            "/api/v1/analysis/conversation-insights/sessions/{session_id}/",
            {
              method: "get",
              params: {
                path: {
                  session_id: id
                }
              }
            }
          );

          return res;
        }
      },

      /** Ask something
       * @param {Object} args
       * @param {import('./conversations').ChatPartner} args.chatPartner
       * @param {string} args.question
       * @param {(answer: string) => void} [args.onAnswer]
       * @param {string} [args.startDate] Define start and end date for data; Expects UTC time string.
       * @param {string} [args.endDate] Define start and end date for data; Expects UTC time string.
       * @param {"sync" | "auto"} [args.processingMode]
       */
      ask: async ({
        chatPartner,
        startDate,
        endDate,
        question,
        onAnswer,
        processingMode = "sync"
      }) => {
        /**  @type {{assistant_id?: string, group_chat_id?: string}} */
        const target = { assistant_id: undefined, group_chat_id: undefined };

        if (chatPartner.type === "assistant" || chatPartner.type === "default-assistant") {
          target.assistant_id = chatPartner.id;
        } else if (chatPartner.type === "group-chat") {
          target.group_chat_id = chatPartner.id;
        } else {
          throw new IntricError(
            "Asking a question requires one of 'assistant' or 'groupChat' to be specified",
            "CONNECTION",
            0,
            0
          );
        }

        if (processingMode === "auto") {
          const response = await client.fetch("/api/v1/analysis/conversation-insights/", {
            method: "post",
            params: {
              query: {
                ...target,
                from_date: startDate,
                to_date: endDate,
                include_followups: true,
                processing_mode: "auto"
              }
            },
            requestBody: { "application/json": { question, stream: false } }
          });

          if (response?.is_async && response?.job_id) {
            return { answer: "", isAsync: true, jobId: response.job_id, status: response.status };
          }

          return {
            answer: response?.answer ?? "",
            isAsync: false,
            jobId: null,
            status: response?.status ?? "completed"
          };
        }

        let answer = "";

        await client.stream(
          "/api/v1/analysis/conversation-insights/",
          {
            params: {
              query: {
                ...target,
                from_date: startDate,
                to_date: endDate,
                include_followups: true
              }
            },
            requestBody: { "application/json": { question, stream: true } }
          },
          {
            onMessage: (ev) => {
              if (ev.data == "") return;
              try {
                const data = JSON.parse(ev.data);
                if (data.answer) {
                  answer += data.answer;
                  onAnswer?.(data.answer);
                }
              } catch (e) {
                return;
              }
            }
          }
        );

        return { answer };
      },

      /**
       * Get async conversation-insights analysis job status.
       * @param {{ jobId: string }} args
       */
      getJobStatus: async ({ jobId }) => {
        const res = await client.fetch("/api/v1/analysis/conversation-insights/jobs/{job_id}/", {
          method: "get",
          params: {
            path: { job_id: jobId }
          }
        });
        return res;
      }
    }
  };
}
