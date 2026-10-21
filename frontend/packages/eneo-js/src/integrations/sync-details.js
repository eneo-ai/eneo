/** @typedef {import('../types/schema').components['schemas']['IntegrationSyncDetails']} Details */
/** @typedef {import('../types/schema').components['schemas']['IntegrationSyncDetailsRequest']} Request */
/** @typedef {import('../types/schema').components['schemas']['IntegrationSyncDetailsList']} Response */
/** @typedef {{spaceId: string, id: string, offset: number, limit: number, resolve: (value: Details) => void, reject: (reason: unknown) => void}} Read */

export const SYNC_DETAILS_BATCH_SIZE = 50;

/**
 * Transport batching for source pages. Cache ownership stays with each app.
 * Reads started in the same turn share a request; large sources drain serially
 * in bounded batches. There is no result cache, so a retry always reads again.
 * @param {(spaceId: string, request: Request) => Promise<Response>} fetchBatch
 */
export function createSyncDetailsLoader(fetchBatch) {
  /** @type {Read[]} */
  let pending = [];
  let scheduled = false;

  async function drain() {
    // Only this turn's reads drain together. A later user action or revision
    // must not wait for a slow older page from an earlier turn.
    let remaining = pending;
    pending = [];
    scheduled = false;
    while (remaining.length > 0) {
      const first = remaining[0];
      /** @type {Read[]} */
      const batch = [];
      /** @type {Map<string, number>} */
      const offsets = new Map();
      remaining = remaining.filter((read) => {
        if (read.spaceId !== first.spaceId || read.limit !== first.limit) return true;
        if (offsets.has(read.id) && offsets.get(read.id) !== read.offset) return true;
        if (!offsets.has(read.id) && offsets.size === SYNC_DETAILS_BATCH_SIZE) return true;
        offsets.set(read.id, read.offset);
        batch.push(read);
        return false;
      });
      try {
        const response = await fetchBatch(first.spaceId, {
          items: [...offsets].map(([integration_knowledge_id, offset]) => ({
            integration_knowledge_id,
            offset
          })),
          limit: first.limit
        });
        const byId = new Map(response.items.map((item) => [item.integration_knowledge_id, item]));
        if (
          byId.size !== offsets.size ||
          response.items.length !== offsets.size ||
          [...offsets].some(([id, offset]) => byId.get(id)?.history.offset !== offset)
        ) {
          throw new Error("Incomplete integration sync details response");
        }
        for (const read of batch) {
          const item = byId.get(read.id);
          if (item) read.resolve(item);
        }
      } catch (error) {
        for (const read of batch) read.reject(error);
      }
    }
  }

  /**
   * @param {string} spaceId
   * @param {string} id
   * @param {number} [offset]
   * @param {number} [limit]
   * @returns {Promise<Details>}
   */
  return (spaceId, id, offset = 0, limit = 10) =>
    new Promise((resolve, reject) => {
      pending.push({ spaceId, id, offset, limit, resolve, reject });
      if (!scheduled) {
        scheduled = true;
        queueMicrotask(() => void drain());
      }
    });
}
