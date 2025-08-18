/** @typedef {import('../client/client').IntricError} IntricError */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initUsage(client) {
  return {
    tokens: {
      /**
       * List token usage status for current tenant
       * @param {{startDate: string, endDate: string}} [params] Define start and end date for data; Expects UTC time string.
       * @throws {IntricError}
       * */
      getSummary: async (params) => {
        const res = await client.fetch("/api/v1/token-usage/", {
          method: "get",
          params: {
            query: {
              start_date: params?.startDate,
              end_date: params?.endDate
            }
          }
        });
        return res;
      },

      /**
       * List token usage status aggregated by users for current tenant
       * @param {{startDate: string, endDate: string, page: number, perPage: number, sortBy: import("../types/resources").UserSortBy, sortOrder: string}} [params] Define start and end date for data; Expects UTC time string.
       * @throws {IntricError}
       * */
      getUsersSummary: async (params) => {
        const res = await client.fetch("/api/v1/token-usage/users", {
          method: "get",
          params: {
            query: {
              start_date: params?.startDate,
              end_date: params?.endDate,
              page: params?.page,
              per_page: params?.perPage,
              sort_by: params?.sortBy,
              sort_order: params?.sortOrder
            }
          }
        });
        return res;
      },

      /**
       * Get summary for a specific user without fetching all users
       * @param {string} userId User ID to get summary for
       * @param {{startDate: string, endDate: string}} [params] Define start and end date for data; Expects UTC time string.
       * @throws {IntricError}
       * */
      getUserSummary: async (userId, params) => {
        const res = await client.fetch(`/api/v1/token-usage/users/{user_id}/summary`, {
          method: "get",
          params: {
            path: {
              user_id: userId
            },
            query: {
              start_date: params?.startDate,
              end_date: params?.endDate
            }
          }
        });
        return res;
      },

      /**
       * Get model breakdown for a specific user
       * @param {string} userId User ID to get breakdown for
       * @param {{startDate: string, endDate: string}} [params] Define start and end date for data; Expects UTC time string.
       * @throws {IntricError}
       * */
      getUserModelBreakdown: async (userId, params) => {
        const res = await client.fetch(`/api/v1/token-usage/users/{user_id}`, {
          method: "get",
          params: {
            path: {
              user_id: userId
            },
            query: {
              start_date: params?.startDate,
              end_date: params?.endDate
            }
          }
        });
        return res;
      }
    },

    storage: {
      /**
       * List storage status and settings for current tenant
       * @throws {IntricError}
       * */
      getSummary: async () => {
        const res = await client.fetch("/api/v1/storage/", { method: "get" });
        return res;
      },

      /**
       * List all non-personal spaces of this tenant and their corresponding sizes
       *
       * @throws {IntricError}
       */
      listSpaces: async () => {
        const res = await client.fetch("/api/v1/storage/spaces/", {
          method: "get"
        });
        return res.items;
      }
    }
  };
}
