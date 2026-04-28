/** @typedef {import('../client/client').IntricError} IntricError */

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initFlows(client) {
  /** @param {string} path @param {object} options */
  const _fetch = (path, options) => /** @type {any} */ (client).fetch(path, options);
  const _textEncoder = new TextEncoder();

  /**
   * @param {any} value
   * @returns {any}
   */
  const _stableSortObjectKeys = (value) => {
    if (Array.isArray(value)) {
      return value.map(_stableSortObjectKeys);
    }
    if (
      value &&
      typeof value === "object" &&
      !(value instanceof Date) &&
      !(value instanceof File)
    ) {
      return Object.keys(value)
        .sort()
        .reduce((acc, key) => {
          acc[key] = _stableSortObjectKeys(value[key]);
          return acc;
        }, /** @type {Record<string, any>} */ ({}));
    }
    return value;
  };

  /**
   * @param {ArrayBuffer} buffer
   * @returns {string}
   */
  const _hexFromBuffer = (buffer) =>
    Array.from(new Uint8Array(buffer))
      .map((byte) => byte.toString(16).padStart(2, "0"))
      .join("");

  /**
   * @param {Record<string, {file_ids?: string[]}> | undefined} step_inputs
   * @returns {Record<string, {file_ids?: string[]}> | undefined}
   */
  const _normalizeStepInputs = (step_inputs) =>
    step_inputs == null
      ? undefined
      : Object.keys(step_inputs)
          .sort()
          .reduce((acc, stepId) => {
            const stepInput = step_inputs[stepId] ?? {};
            acc[stepId] = {
              ..._stableSortObjectKeys(stepInput),
              ...(stepInput.file_ids ? { file_ids: [...stepInput.file_ids].sort() } : {})
            };
            return acc;
          }, /** @type {Record<string, any>} */ ({}));

  /**
   * @param {{
   *   flowId: string,
   *   expectedFlowVersion?: number,
   *   input_payload_json?: any,
   *   step_inputs?: Record<string, {file_ids?: string[]}>,
   *   file_ids?: string[]
   * }} params
   * @returns {{
   *   flow_id: string,
   *   expected_flow_version?: number,
   *   input_payload_json?: any,
   *   step_inputs?: Record<string, {file_ids?: string[]}>,
   *   file_ids?: string[]
   * }}
   */
  const _normalizeRunIntent = ({
    flowId,
    expectedFlowVersion,
    input_payload_json,
    step_inputs,
    file_ids
  }) => {
    const normalizedStepInputs = _normalizeStepInputs(step_inputs);
    return {
      flow_id: flowId,
      ...(expectedFlowVersion != null ? { expected_flow_version: expectedFlowVersion } : {}),
      ...(input_payload_json !== undefined
        ? { input_payload_json: _stableSortObjectKeys(input_payload_json) }
        : {}),
      ...(normalizedStepInputs ? { step_inputs: normalizedStepInputs } : {}),
      ...(file_ids?.length ? { file_ids: [...file_ids].sort() } : {})
    };
  };

  /**
   * @param {{
   *   flowId: string,
   *   expectedFlowVersion?: number,
   *   input_payload_json?: any,
   *   step_inputs?: Record<string, {file_ids?: string[]}>,
   *   file_ids?: string[]
   * }} params
   * @returns {Promise<string>}
   */
  const _deriveUploadIntentIdempotencyKey = async (params) => {
    if (!globalThis.crypto?.subtle) {
      throw new Error("Web Crypto is required to derive Flow run idempotency keys.");
    }

    const normalizedPayload = _normalizeRunIntent(params);
    const digest = await globalThis.crypto.subtle.digest(
      "SHA-256",
      _textEncoder.encode(JSON.stringify(normalizedPayload))
    );
    return `flow-run:${_hexFromBuffer(digest)}`;
  };

  /**
   * @param {{flowId?: string, flow_id?: string}} run
   * @param {string} operation
   * @returns {string}
   */
  const _requireFlowIdForRunRoute = (run, operation) => {
    const flowId = run.flowId ?? run.flow_id;
    if (!flowId) {
      throw new Error(`Flow run ${operation} requires flowId.`);
    }
    return flowId;
  };

  return {
    /**
     * Create a new Flow
     * @param {{spaceId: string, name: string, description?: string, steps?: any[], metadata_json?: any, data_retention_days?: number}} flow
     * @throws {IntricError}
     */
    create: async (flow) => {
      const { spaceId, name, description, steps = [], metadata_json, data_retention_days } = flow;
      return _fetch("/api/v1/flows/", {
        method: "post",
        requestBody: {
          "application/json": {
            space_id: spaceId,
            name,
            description,
            steps,
            metadata_json,
            data_retention_days
          }
        }
      });
    },

    /**
     * List flows in a space
     * @param {{spaceId: string, limit?: number, offset?: number}} params
     * @throws {IntricError}
     */
    list: async ({ spaceId, limit = 50, offset = 0 }) => {
      return _fetch("/api/v1/flows/", {
        method: "get",
        params: { query: { space_id: spaceId, limit, offset } }
      });
    },

    /**
     * Get a flow by id
     * @param {{id: string}} flow
     * @throws {IntricError}
     */
    get: async (flow) => {
      return _fetch(`/api/v1/flows/${flow.id}/`, { method: "get" });
    },

    /**
     * Update a flow
     * @param {{flow: {id: string}, update: object}} params
     * @throws {IntricError}
     */
    update: async ({ flow, update }) => {
      return _fetch(`/api/v1/flows/${flow.id}/`, {
        method: "patch",
        requestBody: { "application/json": update }
      });
    },

    /**
     * Delete a flow
     * @param {{id: string}} flow
     * @returns {Promise<true>}
     * @throws {IntricError}
     */
    delete: async (flow) => {
      await _fetch(`/api/v1/flows/${flow.id}/`, { method: "delete" });
      return true;
    },

    /**
     * Publish a flow
     * @param {{id: string}} flow
     * @throws {IntricError}
     */
    publish: async (flow) => {
      return _fetch(`/api/v1/flows/${flow.id}/publish/`, { method: "post" });
    },

    /**
     * Unpublish a flow (return to draft)
     * @param {{id: string}} flow
     * @throws {IntricError}
     */
    unpublish: async (flow) => {
      return _fetch(`/api/v1/flows/${flow.id}/unpublish/`, { method: "post" });
    },

    /**
     * Get the graph representation of a flow
     * @param {{id: string, run_id?: string}} params
     * @throws {IntricError}
     */
    graph: async ({ id, run_id }) => {
      const query = run_id ? { run_id } : {};
      return _fetch(`/api/v1/flows/${id}/graph/`, {
        method: "get",
        params: { query }
      });
    },

    /**
     * Get effective flow input policy (input type, accepted mimes, size limit).
     * @param {{id: string}} params
     * @throws {IntricError}
     */
    inputPolicy: async ({ id }) => {
      return _fetch(`/api/v1/flows/${id}/input-policy/`, { method: "get" });
    },

    runContract: {
      /**
       * Fetch canonical run contract for runtime step inputs and template readiness.
       * @param {{id: string}} params
       * @throws {IntricError}
       */
      get: async ({ id }) => {
        return _fetch(`/api/v1/flows/${id}/run-contract/`, { method: "get" });
      }
    },

    /**
     * Inspect placeholders in an uploaded DOCX template for a flow.
     * @param {{id: string, fileId: string}} params
     * @throws {IntricError}
     */
    inspectTemplate: async ({ id, fileId }) => {
      return _fetch(`/api/v1/flows/${id}/template-inspect/`, {
        method: "get",
        params: { query: { file_id: fileId } }
      });
    },

    templates: {
      /**
       * List flow-scoped DOCX template assets.
       * @param {{id: string}} params
       * @throws {IntricError}
       */
      list: async ({ id }) => {
        return _fetch(`/api/v1/flows/${id}/template-files/`, {
          method: "get"
        });
      },

      /**
       * Upload a reusable DOCX template asset for Flow template_fill steps.
       * @param {{id: string, file: File, signal?: AbortSignal}} params
       * @throws {IntricError}
       */
      upload: async ({ id, file, signal }) => {
        const formData = new FormData();
        formData.append("upload_file", file);
        return _fetch(`/api/v1/flows/${id}/template-files/`, {
          method: "post",
          requestBody: { "multipart/form-data": formData },
          signal
        });
      },

      /**
       * Inspect placeholders in a flow-scoped DOCX template asset.
       * @param {{id: string, fileId: string}} params
       * @throws {IntricError}
       */
      inspect: async ({ id, fileId }) => {
        return _fetch(`/api/v1/flows/${id}/template-inspect/`, {
          method: "get",
          params: { query: { file_id: fileId } }
        });
      },

      /**
       * Generate signed URL for flow template asset download.
       * @param {{id: string, fileId: string, expiresIn?: number, contentDisposition?: "attachment" | "inline"}} params
       * @throws {IntricError}
       */
      signedUrl: async ({ id, fileId, expiresIn = 3600, contentDisposition = "attachment" }) => {
        return _fetch(`/api/v1/flows/${id}/template-files/${fileId}/signed-url/`, {
          method: "post",
          requestBody: {
            "application/json": {
              expires_in: expiresIn,
              content_disposition: contentDisposition
            }
          }
        });
      }
    },

    steps: {
      runtimeFiles: {
        /**
         * Upload runtime files for a specific flow step.
         * @param {{id: string, stepId: string, file: File, signal?: AbortSignal}} params
         * @throws {IntricError}
         */
        upload: async ({ id, stepId, file, signal }) => {
          const formData = new FormData();
          formData.append("upload_file", file);
          return _fetch(`/api/v1/flows/${id}/steps/${stepId}/runtime-files/`, {
            method: "post",
            requestBody: { "multipart/form-data": formData },
            signal
          });
        }
      }
    },

    files: {
      /**
       * Upload a file scoped to a specific flow.
       * @param {{id: string, file: File, signal?: AbortSignal}} params
       * @throws {IntricError}
       */
      upload: async ({ id, file, signal }) => {
        const formData = new FormData();
        formData.append("upload_file", file);
        return _fetch(`/api/v1/flows/${id}/files/`, {
          method: "post",
          requestBody: { "multipart/form-data": formData },
          signal
        });
      }
    },

    assistants: {
      /**
       * Create a flow-managed assistant owned by the flow.
       * @param {{id: string, name: string}} params
       * @throws {IntricError}
       */
      create: async ({ id, name }) => {
        return _fetch(`/api/v1/flows/${id}/assistants/`, {
          method: "post",
          requestBody: { "application/json": { name } }
        });
      },

      /**
       * Get a flow-managed assistant.
       * @param {{id: string, assistantId: string}} params
       * @throws {IntricError}
       */
      get: async ({ id, assistantId }) => {
        return _fetch(`/api/v1/flows/${id}/assistants/${assistantId}/`, {
          method: "get"
        });
      },

      /**
       * Update a flow-managed assistant.
       * @param {{id: string, assistantId: string, update: object}} params
       * @throws {IntricError}
       */
      update: async ({ id, assistantId, update }) => {
        const body = /** @type {{description?: string | null} & Record<string, any>} */ ({
          ...update
        });
        if (typeof body.description === "string" && body.description.trim() === "") {
          body.description = null;
        }
        return _fetch(`/api/v1/flows/${id}/assistants/${assistantId}/`, {
          method: "patch",
          requestBody: { "application/json": body }
        });
      },

      /**
       * Delete a flow-managed assistant.
       * @param {{id: string, assistantId: string}} params
       * @returns {Promise<true>}
       * @throws {IntricError}
       */
      delete: async ({ id, assistantId }) => {
        await _fetch(`/api/v1/flows/${id}/assistants/${assistantId}/`, {
          method: "delete"
        });
        return true;
      }
    },

    runs: {
      /**
       * Create a flow run
       * @param {{
       *  flow: {id: string},
       *  expected_flow_version?: number,
       *  idempotencyKey?: string,
       *  input_payload_json?: any,
       *  step_inputs?: Record<string, {file_ids: string[]}>,
       *  file_ids?: string[]
       * }} params
       * @throws {IntricError}
       */
      create: async ({
        flow,
        expected_flow_version,
        idempotencyKey,
        input_payload_json,
        step_inputs,
        file_ids
      }) => {
        const normalizedRequest = _normalizeRunIntent({
          flowId: flow.id,
          expectedFlowVersion: expected_flow_version,
          input_payload_json,
          step_inputs,
          file_ids
        });
        delete normalizedRequest.flow_id;
        return _fetch(`/api/v1/flows/${flow.id}/runs/`, {
          method: "post",
          headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
          requestBody: {
            "application/json": normalizedRequest
          }
        });
      },

      /**
       * Derive a stable Idempotency-Key value for upload-driven Flow runs.
       * @param {{
       *  flowId: string,
       *  expectedFlowVersion?: number,
       *  input_payload_json?: any,
       *  step_inputs?: Record<string, {file_ids?: string[]}>,
       *  file_ids?: string[]
       * }} params
       * @returns {Promise<string>}
       */
      deriveUploadIntentIdempotencyKey: async (params) => {
        return _deriveUploadIntentIdempotencyKey(params);
      },

      /**
       * List runs for a flow
       * @param {{flowId: string, limit?: number, offset?: number}} params
       * @throws {IntricError}
       */
      list: async ({ flowId, limit = 50, offset = 0 }) => {
        return _fetch(`/api/v1/flows/${flowId}/runs/`, {
          method: "get",
          params: { query: { limit, offset } }
        });
      },

      /**
       * Get a specific flow run
       * @param {{id: string, flowId: string, flow_id?: string}} run
       * @throws {IntricError}
       */
      get: async (run) => {
        const flowId = _requireFlowIdForRunRoute(run, "get");
        return _fetch(`/api/v1/flows/${flowId}/runs/${run.id}/`, {
          method: "get"
        });
      },

      /**
       * List step outputs for a specific run under a flow.
       * @param {{flowId: string, runId: string}} params
       * @throws {IntricError}
       */
      steps: async ({ flowId, runId }) => {
        return _fetch(`/api/v1/flows/${flowId}/runs/${runId}/steps/`, {
          method: "get"
        });
      },

      /**
       * Cancel a flow run
       * @param {{id: string, flowId: string, flow_id?: string}} run
       * @throws {IntricError}
       */
      cancel: async (run) => {
        const flowId = _requireFlowIdForRunRoute(run, "cancel");
        return _fetch(`/api/v1/flows/${flowId}/runs/${run.id}/cancel/`, {
          method: "post"
        });
      },

      /**
       * Redispatch a stale queued flow run
       * @param {{id: string, flowId: string, flow_id?: string}} run
       * @returns {Promise<import('../types/resources').FlowRunRedispatchResult>}
       * @throws {IntricError}
       */
      redispatch: async (run) => {
        const flowId = _requireFlowIdForRunRoute(run, "redispatch");
        return _fetch(`/api/v1/flows/${flowId}/runs/${run.id}/redispatch/`, {
          method: "post"
        });
      },

      /**
       * Get evidence for a flow run
       * @param {{id: string, flowId: string, flow_id?: string}} run
       * @throws {IntricError}
       */
      evidence: async (run) => {
        const flowId = _requireFlowIdForRunRoute(run, "evidence");
        return _fetch(`/api/v1/flows/${flowId}/runs/${run.id}/evidence/`, {
          method: "get"
        });
      },

      /**
       * Export canonical evidence bundle for a flow run.
       * @param {{id: string, flowId: string, flow_id?: string, format?: "json"}} run
       * @returns {Promise<import('../types/resources').FlowRunEvidenceExport>}
       * @throws {IntricError}
       */
      exportEvidence: async (run) => {
        const flowId = _requireFlowIdForRunRoute(run, "exportEvidence");
        return _fetch(`/api/v1/flows/${flowId}/runs/${run.id}/evidence/export`, {
          method: "get",
          params: {
            query: { format: run.format ?? "json" }
          }
        });
      },

      /**
       * Generate signed URL for a flow run artifact download.
       * Uses tenant-scoped access so any user with flow access can download artifacts.
       * @param {{flowId: string, runId: string, fileId: string, expiresIn?: number, contentDisposition?: "attachment" | "inline"}} params
       * @throws {IntricError}
       */
      artifactSignedUrl: async ({
        flowId,
        runId,
        fileId,
        expiresIn = 3600,
        contentDisposition = "attachment"
      }) => {
        return _fetch(`/api/v1/flows/${flowId}/runs/${runId}/artifacts/${fileId}/signed-url/`, {
          method: "post",
          requestBody: {
            "application/json": {
              expires_in: expiresIn,
              content_disposition: contentDisposition
            }
          }
        });
      }
    }
  };
}
