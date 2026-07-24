/** @typedef {import('../types/resources').InfoBlob} InfoBlob */
/** @typedef {import('../types/resources').Group} Group */
/** @typedef {import('../client/client').EneoError} EneoError */
/** @typedef {import('../types/resources').UploadedFile} UploadedFile */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initFiles(client) {
  /**
   * @param {Object} params
   * @param {string} params.fileId
   * @param {number} [params.expiresIn]
   * @param {"attachment" | "inline"} [params.contentDisposition]
   * @param {"/api/v1/files/{id}/signed-url/" | "/api/v1/files/{id}/original/signed-url/"} endpoint
   */
  const requestSignedUrl = async ({ fileId, expiresIn, contentDisposition }, endpoint) => {
    const expires_in = expiresIn ?? 3600;
    const content_disposition = contentDisposition ?? "inline";

    const res = await client.fetch(endpoint, {
      method: "post",
      params: { path: { id: fileId } },
      requestBody: {
        "application/json": {
          content_disposition,
          expires_in
        }
      }
    });

    // Keep the signed path and token, but use the public host configured by the caller.
    const signedUrl = new URL(res.url);
    const url = new URL(
      `${signedUrl.pathname}${signedUrl.search}${signedUrl.hash}`,
      client.baseUrl
    );

    return {
      url: url.toString(),
      expires_at: res.expires_at
    };
  };

  return {
    /**
     * Upload a supported filetype and start converting it into an `InfoBlob`. Depending on the filetype and size the conversion can take some time,
     * so after a successful upload a `Job` is returned that can be independently tracked.
     * @param {Object} params
     * @param {File} params.file The file to upload
     * @param {(ev: ProgressEvent<EventTarget>) => void} [params.onProgress] Callback to run on upload progress
     * @param {AbortController} [params.abortController] Pass in an AbortController if you want to be able to cancel this upload
     * @returns {Promise<UploadedFile>}
     * @throws {EneoError}
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
     * @throws {EneoError}
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
     * @param {number} [params.expiresIn] Expiry time in seconds (1–3600, default: 3600)
     * @param {"attachment" | "inline"} [params.contentDisposition] Content disposition (default: "inline")
     * @returns {Promise<{url: string, expires_at: number}>}
     * @throws {EneoError}
     * */
    generateSignedUrl: async ({ fileId, expiresIn, contentDisposition }) => {
      return requestSignedUrl(
        { fileId, expiresIn, contentDisposition },
        "/api/v1/files/{id}/signed-url/"
      );
    },

    /**
     * Generate a short-lived signed URL for the exact bytes originally uploaded.
     * Unlike `generateSignedUrl`, this never selects extracted text or another processing representation.
     * @param {Object} params
     * @param {string} params.fileId The file ID
     * @param {number} [params.expiresIn] Expiry time in seconds (default: 3600)
     * @param {"attachment" | "inline"} [params.contentDisposition] Content disposition (default: "inline")
     * @returns {Promise<{url: string, expires_at: number}>}
     * @throws {EneoError}
     * */
    generateOriginalSignedUrl: async ({ fileId, expiresIn, contentDisposition }) => {
      return requestSignedUrl(
        { fileId, expiresIn, contentDisposition },
        "/api/v1/files/{id}/original/signed-url/"
      );
    }
  };
}
