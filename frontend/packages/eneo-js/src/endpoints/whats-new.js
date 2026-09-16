/** @typedef {import('../client/client').EneoError} EneoError */
/** @typedef {import('../types/resources').WhatsNewState} WhatsNewState */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initWhatsNew(client) {
  return {
    /**
     * Get which releases the current user has seen and been told about.
     * @returns {Promise<WhatsNewState>}
     * @throws {EneoError}
     */
    getState: async () => {
      const res = await client.fetch("/api/v1/whats-new/state/", { method: "get" });
      return res;
    },

    /**
     * Record that the current user has opened the What's new page for a release.
     * @param {string} version Release id as written in releases.json (e.g. "2.2.0")
     * @returns {Promise<WhatsNewState>}
     * @throws {EneoError}
     */
    markSeen: async (version) => {
      const res = await client.fetch("/api/v1/whats-new/seen/", {
        method: "put",
        requestBody: { "application/json": { version } }
      });
      return res;
    },

    /**
     * Record that the current user has been shown the announcement for a release.
     * @param {string} version Release id as written in releases.json (e.g. "2.2.0")
     * @returns {Promise<WhatsNewState>}
     * @throws {EneoError}
     */
    markAnnounced: async (version) => {
      const res = await client.fetch("/api/v1/whats-new/announced/", {
        method: "put",
        requestBody: { "application/json": { version } }
      });
      return res;
    }
  };
}
