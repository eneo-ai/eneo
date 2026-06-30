/** @typedef {import('../types/resources').InfoBlob} InfoBlob */
/** @typedef {import('../types/resources').Group} Group */
/** @typedef {import('../client/client').EneoError} EneoError */
/** @typedef {import('../types/resources').Job} Job */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initInfoBlobs(client) {
  return {
    /**
     * List all info-blobs; text porperty will be null.
     * @returns {Promise<Omit<InfoBlob, "text">[]>}
     * @throws {EneoError}
     * */
    list: async () => {
      const res = await client.fetch("/api/v1/info-blobs/", { method: "get" });
      return res.items;
    },

    /**
     * Get info and text of a blob via its id.
     * @param  {{id: string} | InfoBlob} blob Info-Blob
     * @returns {Promise<InfoBlob>} Full info about the queried group
     * @throws {EneoError}
     * */
    get: async (blob) => {
      const { id } = blob;
      const res = await client.fetch("/api/v1/info-blobs/{id}/", {
        method: "get",
        params: { path: { id } }
      });
      return res;
    },

    /**
     * Create a new `InfoBlob` by submitting raw text. Requires a parent `group_id` to be set
     * @param {{group_id: string, text: string; metadata?: { url?: string; title?: string}}} blob The `InfoBlob` to add
     * @returns {Promise<InfoBlob[]>}
     * @throws {EneoError}
     * */
    create: async (blob) => {
      const { group_id: id } = blob;
      const res = await client.fetch("/api/v1/groups/{id}/info-blobs/", {
        method: "post",
        params: { path: { id } },
        requestBody: { "application/json": { info_blobs: [blob] } }
      });
      return res.items;
    },

    /**
     * Upload a supported filetype and start converting it into an `InfoBlob`. Depending on the filetype and size the conversion can take some time,
     * so after a successful upload a `Job` is returned that can be independently tracked.
     * @param {Object} params
     * @param {string} params.group_id Destination group for the uploaded files
     * @param {File} params.file The file to upload
     * @param {(ev: ProgressEvent<EventTarget>) => void} [params.onProgress] Callback to run on upload progress
     * @returns {Promise<Job>}
     * @throws {EneoError}
     * */
    upload: async ({ group_id, file, onProgress }) => {
      const formData = new FormData();
      formData.append("file", file);
      const res = await client.xhr(
        "/api/v1/groups/{id}/info-blobs/upload/",
        {
          method: "post",
          params: { path: { id: group_id } },
          //@ts-expect-error Typing for multipart/formdata upload does currently not work correctly
          requestBody: { "multipart/form-data": formData }
        },
        {
          onProgress
        }
      );
      return res;
    },

    /**
     * Update an existing info-blob's metadata.
     * @param {Object} params
     * @param {{id: string} | InfoBlob} params.blob
     * @param {{metadata: {url?: string, title?: string}} | InfoBlob} params.update - Either provide the updated blob or the parameters to update.
     * @returns {Promise<InfoBlob>} The updated blob
     * @throws {EneoError}
     * */
    update: async ({ blob, update }) => {
      const { id } = blob;
      const res = await client.fetch("/api/v1/info-blobs/{id}/", {
        method: "post",
        params: { path: { id } },
        requestBody: { "application/json": update }
      });
      return res;
    },

    /**
     * Delete the specified blobl.
     * @param {{id: string} | InfoBlob} blob - Either provide the blob to delete or a specified id.
     * @returns {Promise<InfoBlob>} The deleted blob
     * @throws {EneoError}
     *  */
    delete: async (blob) => {
      const { id } = blob;
      const res = await client.fetch("/api/v1/info-blobs/{id}/", {
        method: "delete",
        params: { path: { id } }
      });
      return res;
    }
  };
}
