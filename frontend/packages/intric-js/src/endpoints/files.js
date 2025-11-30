/** @typedef {import('../types/resources').InfoBlob} InfoBlob */
/** @typedef {import('../types/resources').Group} Group */
/** @typedef {import('../client/client').IntricError} IntricError */
/** @typedef {import('../types/resources').UploadedFile} UploadedFile */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initFiles(client) {
  return {
    /**
     * Upload a supported filetype and start converting it into an `InfoBlob`. Depending on the filetype and size the conversion can take some time,
     * so after a successful upload a `Job` is returned that can be independently tracked.
     * @param {Object} params
     * @param {File} params.file The file to upload
     * @param {(ev: ProgressEvent<EventTarget>) => void} [params.onProgress] Callback to run on upload progress
     * @param {AbortController} [params.abortController] Pass in an AbortController if you want to be able to cancel this upload
     * @returns {Promise<UploadedFile>}
     * @throws {IntricError}
     * */
    upload: async ({ file, onProgress, abortController }) => {
      const formData = new FormData();
      formData.append("upload_file", file);
      const res = await client.xhr(
        "/api/v1/files/",
        {
          method: "post",
          //@ts-expect-error Typing for multipart/formdata upload does currently not work correctly
          requestBody: { "multipart/form-data": formData }
        },
        {
          onProgress
        },
        abortController
      );
      return res;
    },

    /**
     * Delete a file from the database
     * @param {Object} params
     * @param {string} params.fileId The file to delete
     * @throws {IntricError}
     * */
    delete: async ({ fileId }) => {
      client.fetch(`/api/v1/files/{id}/`, {
        method: "delete",
        params: { path: { id: fileId } }
      });
    },

    /**
     * Generate a signed URL to access the uploaded file (returns full response with expires_at)
     * @param {Object} params
     * @param {string} params.fileId The file ID
     * @param {number} [params.expiresIn] Expiry time in seconds (default: 3600)
     * @param {"attachment" | "inline"} [params.contentDisposition] Content disposition (default: "inline")
     * @returns {Promise<{url: string, expires_at: number}>}
     * @throws {IntricError}
     * */
    generateSignedUrl: async ({ fileId, expiresIn, contentDisposition }) => {
      const expires_in = expiresIn ?? 3600;
      const content_disposition = contentDisposition ?? "inline";

      const res = await client.fetch(`/api/v1/files/{id}/signed-url/`, {
        method: "post",
        params: { path: { id: fileId } },
        requestBody: {
          "application/json": {
            content_disposition,
            expires_in
          }
        }
      });

      // The backend does not necessarily know the protocol it uses, as it sits behind a reverse proxy
      const url = new URL(res.url);
      url.protocol = client.baseUrl.protocol;

      return {
        url: url.toString(),
        expires_at: res.expires_at
      };
    }
  };
}
