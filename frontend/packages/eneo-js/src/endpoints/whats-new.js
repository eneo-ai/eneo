/** @typedef {import('../client/client').EneoError} EneoError */
/** @typedef {import('../types/resources').WhatsNewSeen} WhatsNewSeen */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initWhatsNew(client) {
  return {
    /**
     * Get the newest release the current user has opened on the What's new page.
     * @returns {Promise<WhatsNewSeen>}
     * @throws {EneoError}
     */
    getSeen: async () => {
      const res = await client.fetch("/api/v1/whats-new/seen/", { method: "get" });
      return res;
    },

    /**
     * Record that the current user has opened the What's new page for a release.
     * @param {string} version Release version as written in releases.json (e.g. "2.2.0")
     * @returns {Promise<WhatsNewSeen>}
     * @throws {EneoError}
     */
    markSeen: async (version) => {
      const res = await client.fetch("/api/v1/whats-new/seen/", {
        method: "put",
        requestBody: { "application/json": { version } }
      });
      return res;
    }
  };
}
