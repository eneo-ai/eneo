/**
 * Fetch like implementation of an XHR with callbacks. Use this if you need to track request progress, e.g. on an upload.
 * @param {string} url
 * @param {Object} options
 * @param {string} options.method
 * @param {Record<string, string>} options.headers
 * @param {XMLHttpRequestBodyInit} options.body
 * @param {Object} callbacks
 * @param {(ev: ProgressEvent) => void} [callbacks.onProgress]
 * @param {(xhr: XMLHttpRequest) => void} [callbacks.onError]
 * @param {(xhr: XMLHttpRequest) => void} [callbacks.onTimeout]
 * @param {AbortController | undefined} abortController
 */
export function xhr(
  url,
  { method, headers, body },
  { onProgress, onError, onTimeout },
  abortController
) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    if (abortController) {
      abortController.signal.onabort = () => {
        xhr.abort();
        reject(new Error("Cancelled after receiving abort signal."));
      };
    }
    xhr.open(method, url);
    Object.entries(headers).forEach(([name, value]) => {
      xhr.setRequestHeader(name, value);
    });
    xhr.upload.onprogress = (ev) => {
      onProgress?.(ev);
    };
    xhr.onerror = () => {
      onError?.(xhr);
      reject();
    };
    xhr.ontimeout = () => {
      onTimeout?.(xhr);
      reject();
    };
    xhr.onload = () => {
      if (xhr.readyState === xhr.DONE) {
        resolve(
          new Response(xhr.responseText, {
            status: xhr.status,
            statusText: xhr.statusText,
            headers: parseXhrResponseHeaders(xhr)
          })
        );
      }
    };
    xhr.send(body);
  });
}

/**
 * @param {XMLHttpRequest} xhr
 * @returns {Record<string, string>}
 */
function parseXhrResponseHeaders(xhr) {
  /** @type {Record<string, string>} */
  let parsedHeaders = {};
  const headers = xhr.getAllResponseHeaders().split("\u000d\u000a");
  headers.forEach((header) => {
    const [title, value] = header.split("\u003a\u0020");
    if (title !== "" && value !== undefined) {
      parsedHeaders[title] = value;
    }
  });
  return parsedHeaders;
}
