/** @typedef {import('../client/client').EneoError} EneoError */
/** @typedef {NonNullable<import('../types/schema').operations["list_flow_runs"]["parameters"]["query"]>} FlowRunListQuery */
/** @typedef {NonNullable<import('../types/schema').operations["export_flow_run_evidence"]["parameters"]["query"]>} FlowRunEvidenceExportQuery */
/** @typedef {import('../types/schema').operations["rerun_flow_run_step"]["requestBody"]["content"]["application/json"]} FlowRunStepRerunRequest */
/** @typedef {import('../types/schema').operations["rerun_flow_run_step"]["responses"][202]["content"]["application/json"]} FlowRunStepRerunResponse */
import { FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS } from "../flows/flow-run-reserved-input-payload-keys.js";

const FLOW_PACKAGE_OMITTED_MCP_ASSISTANT_COUNT_HEADER = "Eneo-Package-Omitted-Mcp-Assistant-Count";

/**
 * @param {import('../types/fetch').EneoBinaryResponse} response
 * @returns {import('../types/resources').FlowPackageExportResponse}
 */
function withFlowPackageOmissions(response) {
  const headerValue = response.headers.get(FLOW_PACKAGE_OMITTED_MCP_ASSISTANT_COUNT_HEADER);
  if (headerValue === null) return { ...response, omissions: [] };

  if (!/^[1-9]\d*$/.test(headerValue)) {
    throw new Error("Flow package export returned an invalid MCP omission count.");
  }
  const count = Number(headerValue);
  if (!Number.isSafeInteger(count)) {
    throw new Error("Flow package export returned an invalid MCP omission count.");
  }
  return {
    ...response,
    omissions: [{ kind: "mcp_attachment", count }]
  };
}

/**
 * @param {import('../client/client').Client} client Provide a client with which to call the endpoints
 */
export function initFlows(client) {
  const _fetch = client.fetch;
  /** @type {import('../types/fetch').EneoBinaryFetchFunction} */
  const _binaryFetch = (path, options) => {
    if (!("binaryFetch" in client) || typeof client.binaryFetch !== "function") {
      throw new Error("Flow package export requires a client with binaryFetch support.");
    }
    return client.binaryFetch(path, options);
  };
  const _textEncoder = new TextEncoder();

  /**
   * Sort object keys for stable JSON while preserving array order.
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

  /** @returns {Error & {code: string, status: number}} */
  const _removedTopLevelFileIdsError = () => {
    const error = /** @type {Error & {code: string, status: number}} */ (
      new Error("Top-level file_ids is no longer supported. Use step_inputs[stepId].file_ids.")
    );
    error.code = "flow_run_top_level_file_ids_not_supported";
    error.status = 400;
    return error;
  };

  /** @param {unknown} file_ids */
  const _rejectTopLevelFileIds = (file_ids) => {
    if (file_ids !== undefined) {
      throw _removedTopLevelFileIdsError();
    }
  };

  /** @type {ReadonlySet<string>} */
  const _reservedInputPayloadKeys = new Set(FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS);

  /** @param {unknown} input_payload_json */
  const _rejectReservedInputPayloadKeys = (input_payload_json) => {
    if (
      !input_payload_json ||
      Array.isArray(input_payload_json) ||
      typeof input_payload_json !== "object"
    ) {
      return;
    }
    const keys = Object.keys(input_payload_json).filter((key) =>
      _reservedInputPayloadKeys.has(key)
    );
    if (keys.length === 0) {
      return;
    }
    const error = /** @type {Error & {code: string, status: number, keys: string[]}} */ (
      new Error("input_payload_json contains reserved Flow run orchestration keys.")
    );
    error.code = "flow_run_reserved_input_payload_key";
    error.status = 400;
    error.keys = keys.sort();
    throw error;
  };

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
            acc[stepId] = _stableSortObjectKeys(step_inputs[stepId] ?? {});
            return acc;
          }, /** @type {Record<string, any>} */ ({}));

  /**
   * @param {{
   *   flowId: string,
   *   expectedFlowVersion?: number,
   *   input_payload_json?: any,
   *   step_inputs?: Record<string, {file_ids?: string[]}>
   * }} params
   * @returns {{
   *   flow_id: string,
   *   expected_flow_version?: number,
   *   input_payload_json?: any,
   *   step_inputs?: Record<string, {file_ids?: string[]}>
   * }}
   */
  const _normalizeRunIntent = ({
    flowId,
    expectedFlowVersion,
    input_payload_json,
    step_inputs
  }) => {
    const normalizedStepInputs = _normalizeStepInputs(step_inputs);
    return {
      flow_id: flowId,
      ...(expectedFlowVersion != null ? { expected_flow_version: expectedFlowVersion } : {}),
      ...(input_payload_json !== undefined
        ? { input_payload_json: _stableSortObjectKeys(input_payload_json) }
        : {}),
      ...(normalizedStepInputs ? { step_inputs: normalizedStepInputs } : {})
    };
  };

  /**
   * @param {{
   *   expected_flow_version?: number,
   *   input_payload_json?: any,
   *   step_inputs?: Record<string, {file_ids?: string[]}>
   * }} params
   * @returns {{
   *   expected_flow_version?: number,
   *   input_payload_json?: any,
   *   step_inputs?: Record<string, {file_ids?: string[]}>
   * }}
   */
  const _buildRunRequestBody = ({ expected_flow_version, input_payload_json, step_inputs }) => {
    const normalizedStepInputs = _normalizeStepInputs(step_inputs);
    return {
      ...(expected_flow_version != null ? { expected_flow_version } : {}),
      ...(input_payload_json !== undefined
        ? { input_payload_json: _stableSortObjectKeys(input_payload_json) }
        : {}),
      ...(normalizedStepInputs ? { step_inputs: normalizedStepInputs } : {})
    };
  };

  /**
   * @param {{
   *   flowId: string,
   *   expectedFlowVersion?: number,
   *   input_payload_json?: any,
   *   step_inputs?: Record<string, {file_ids?: string[]}>,
   *   file_ids?: never
   * }} params
   * @returns {Promise<string>}
   */
  const _deriveUploadIntentIdempotencyKey = async (params) => {
    _rejectTopLevelFileIds(params.file_ids);
    _rejectReservedInputPayloadKeys(params.input_payload_json);
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
     * @throws {EneoError}
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
     * @throws {EneoError}
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
     * @throws {EneoError}
     */
    get: async (flow) => {
      return _fetch("/api/v1/flows/{id}/", {
        method: "get",
        params: { path: { id: flow.id } }
      });
    },

    /**
     * Update a flow
     * @param {{flow: {id: string}, update: object}} params
     * @throws {EneoError}
     */
    update: async ({ flow, update }) => {
      return _fetch("/api/v1/flows/{id}/", {
        method: "patch",
        params: { path: { id: flow.id } },
        requestBody: { "application/json": update }
      });
    },

    /**
     * Delete a flow
     * @param {{id: string}} flow
     * @returns {Promise<true>}
     * @throws {EneoError}
     */
    delete: async (flow) => {
      await _fetch("/api/v1/flows/{id}/", {
        method: "delete",
        params: { path: { id: flow.id } }
      });
      return true;
    },

    /**
     * Publish a flow
     * @param {{id: string}} flow
     * @throws {EneoError}
     */
    publish: async (flow) => {
      return _fetch("/api/v1/flows/{id}/publish/", {
        method: "post",
        params: { path: { id: flow.id } }
      });
    },

    /**
     * Unpublish a flow (return to draft)
     * @param {{id: string}} flow
     * @throws {EneoError}
     */
    unpublish: async (flow) => {
      return _fetch("/api/v1/flows/{id}/unpublish/", {
        method: "post",
        params: { path: { id: flow.id } }
      });
    },

    /**
     * Get the graph representation of a flow
     * @param {{id: string, run_id?: string}} params
     * @throws {EneoError}
     */
    graph: async ({ id, run_id }) => {
      const query = run_id ? { run_id } : {};
      return _fetch("/api/v1/flows/{id}/graph/", {
        method: "get",
        params: { path: { id }, query }
      });
    },

    packages: {
      /**
       * Validate a portable Flow package before selecting a target space.
       * @param {{file: File, signal?: AbortSignal}} params
       * @throws {EneoError}
       */
      validate: async ({ file, signal }) => {
        const formData = new FormData();
        formData.append("package_file", file);
        return _fetch("/api/v1/flow-packages/validate/", {
          method: "post",
          requestBody: { "multipart/form-data": formData },
          signal
        });
      },

      /**
       * Preview package dependency resolution for a target space.
       * @param {{spaceId: string, file: File, signal?: AbortSignal}} params
       * @throws {EneoError}
       */
      createImportPlan: async ({ spaceId, file, signal }) => {
        const formData = new FormData();
        formData.append("package_file", file);
        return _fetch("/api/v1/spaces/{id}/flow-packages/import-plan/", {
          method: "post",
          params: { path: { id: spaceId } },
          requestBody: { "multipart/form-data": formData },
          signal
        });
      },

      /**
       * Import a package into a target space as a draft Flow.
       * @param {{spaceId: string, packageBase64: string, expectedContentChecksum: string, expectedTargetState: import('../types/resources').FlowPackageImportTargetState, selectedBindings?: import('../types/resources').FlowPackageImportResourceBinding[]}} params
       * @throws {EneoError}
       */
      importDraft: async ({
        spaceId,
        packageBase64,
        expectedContentChecksum,
        expectedTargetState,
        selectedBindings = []
      }) => {
        return _fetch("/api/v1/spaces/{id}/flow-packages/imports/", {
          method: "post",
          params: { path: { id: spaceId } },
          requestBody: {
            "application/json": {
              package_base64: packageBase64,
              expected_content_checksum: expectedContentChecksum,
              expected_target_state: expectedTargetState,
              selected_bindings: selectedBindings
            }
          }
        });
      },

      /**
       * Export a draft Flow as a portable package bundle.
       * @param {{id: string, packageId: string, packageVersion: string, name: string, description?: string, signal?: AbortSignal}} params
       * @returns {Promise<import('../types/resources').FlowPackageExportResponse>}
       * @throws {EneoError}
       */
      export: async ({ id, packageId, packageVersion, name, description = "", signal }) => {
        const response = await _binaryFetch("/api/v1/flows/{id}/package-exports/", {
          method: "post",
          params: { path: { id } },
          requestBody: {
            "application/json": {
              package_id: packageId,
              package_version: packageVersion,
              name,
              description
            }
          },
          signal
        });
        return withFlowPackageOmissions(response);
      }
    },

    published: {
      /**
       * Fetch the service-key-safe published runtime projection for a Flow.
       * @param {string | {id: string}} flowOrId
       * @throws {EneoError}
       */
      get: async (flowOrId) => {
        const id = typeof flowOrId === "string" ? flowOrId : flowOrId.id;
        return _fetch("/api/v1/flows/{id}/published/", {
          method: "get",
          params: { path: { id } }
        });
      }
    },

    runContract: {
      /**
       * Fetch canonical run contract for runtime step inputs and template readiness.
       * @param {{id: string}} params
       * @throws {EneoError}
       */
      get: async ({ id }) => {
        return _fetch("/api/v1/flows/{id}/run-contract/", {
          method: "get",
          params: { path: { id } }
        });
      }
    },

    /**
     * Inspect placeholders in an uploaded DOCX template for a flow.
     * @param {{id: string, fileId: string}} params
     * @throws {EneoError}
     */
    inspectTemplate: async ({ id, fileId }) => {
      return _fetch("/api/v1/flows/{id}/template-inspect/", {
        method: "get",
        params: { path: { id }, query: { file_id: fileId } }
      });
    },

    templates: {
      /**
       * List flow-scoped DOCX template assets.
       * @param {{id: string}} params
       * @throws {EneoError}
       */
      list: async ({ id }) => {
        return _fetch("/api/v1/flows/{id}/template-files/", {
          method: "get",
          params: { path: { id } }
        });
      },

      /**
       * Upload a reusable DOCX template asset for Flow template_fill steps.
       * @param {{id: string, file: File, signal?: AbortSignal}} params
       * @throws {EneoError}
       */
      upload: async ({ id, file, signal }) => {
        const formData = new FormData();
        formData.append("upload_file", file);
        return _fetch("/api/v1/flows/{id}/template-files/", {
          method: "post",
          params: { path: { id } },
          requestBody: { "multipart/form-data": formData },
          signal
        });
      },

      /**
       * Delete a flow-scoped DOCX template asset.
       * @param {{id: string, fileId: string, signal?: AbortSignal}} params
       * @throws {EneoError}
       */
      delete: async ({ id, fileId, signal }) => {
        return _fetch("/api/v1/flows/{id}/template-files/{file_id}/", {
          method: "delete",
          params: { path: { id, file_id: fileId } },
          signal
        });
      },

      /**
       * Inspect placeholders in a flow-scoped DOCX template asset.
       * @param {{id: string, fileId: string}} params
       * @throws {EneoError}
       */
      inspect: async ({ id, fileId }) => {
        return _fetch("/api/v1/flows/{id}/template-inspect/", {
          method: "get",
          params: { path: { id }, query: { file_id: fileId } }
        });
      },

      /**
       * Generate signed URL for flow template asset download.
       * @param {{id: string, fileId: string, expiresIn?: number, contentDisposition?: "attachment" | "inline"}} params
       * @throws {EneoError}
       */
      signedUrl: async ({ id, fileId, expiresIn = 3600, contentDisposition = "attachment" }) => {
        return _fetch("/api/v1/flows/{id}/template-files/{file_id}/signed-url/", {
          method: "post",
          params: { path: { id, file_id: fileId } },
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
         * Upload runtime files for a specific flow step. Pass onProgress to use
         * XHR progress events and keep long browser uploads alive while bytes
         * continue to transfer. The returned file id may be reused under
         * multiple compatible step_inputs entries when creating the run.
         * @param {{id: string, stepId: string, file: File, signal?: AbortSignal, abortController?: AbortController, onProgress?: (ev: ProgressEvent) => void}} params
         * @throws {EneoError}
         */
        upload: async ({ id, stepId, file, signal, abortController, onProgress }) => {
          const formData = new FormData();
          formData.append("upload_file", file);
          if (onProgress || abortController) {
            const controller = abortController ?? new AbortController();
            if (signal?.aborted) {
              controller.abort();
            } else {
              signal?.addEventListener("abort", () => controller.abort(), { once: true });
            }
            return client.xhr(
              "/api/v1/flows/{id}/steps/{step_id}/runtime-files/",
              {
                method: "post",
                params: { path: { id, step_id: stepId } },
                requestBody: { "multipart/form-data": formData }
              },
              { onProgress },
              controller
            );
          }
          return _fetch("/api/v1/flows/{id}/steps/{step_id}/runtime-files/", {
            method: "post",
            params: { path: { id, step_id: stepId } },
            requestBody: { "multipart/form-data": formData },
            signal
          });
        },

        /**
         * Delete an orphan runtime file before it is attached to a flow run.
         * Files already persisted in run input or output state return a typed
         * 409 conflict from the API.
         * @param {{id: string, fileId: string, signal?: AbortSignal}} params
         * @throws {EneoError}
         */
        delete: async ({ id, fileId, signal }) => {
          return _fetch("/api/v1/flows/{id}/runtime-files/{file_id}/", {
            method: "delete",
            params: { path: { id, file_id: fileId } },
            signal
          });
        }
      }
    },

    assistants: {
      /**
       * Create a flow-managed assistant owned by the flow.
       * @param {{id: string, name: string}} params
       * @throws {EneoError}
       */
      create: async ({ id, name }) => {
        return _fetch("/api/v1/flows/{id}/assistants/", {
          method: "post",
          params: { path: { id } },
          requestBody: { "application/json": { name } }
        });
      },

      /**
       * Get a flow-managed assistant.
       * @param {{id: string, assistantId: string}} params
       * @throws {EneoError}
       */
      get: async ({ id, assistantId }) => {
        return _fetch("/api/v1/flows/{id}/assistants/{assistant_id}/", {
          method: "get",
          params: { path: { id, assistant_id: assistantId } }
        });
      },

      /**
       * Update a flow-managed assistant.
       * @param {{id: string, assistantId: string, update: object}} params
       * @throws {EneoError}
       */
      update: async ({ id, assistantId, update }) => {
        const body = /** @type {{description?: string | null} & Record<string, any>} */ ({
          ...update
        });
        if (typeof body.description === "string" && body.description.trim() === "") {
          body.description = null;
        }
        return _fetch("/api/v1/flows/{id}/assistants/{assistant_id}/", {
          method: "patch",
          params: { path: { id, assistant_id: assistantId } },
          requestBody: { "application/json": body }
        });
      },

      /**
       * Delete a flow-managed assistant.
       * @param {{id: string, assistantId: string}} params
       * @returns {Promise<true>}
       * @throws {EneoError}
       */
      delete: async ({ id, assistantId }) => {
        await _fetch("/api/v1/flows/{id}/assistants/{assistant_id}/", {
          method: "delete",
          params: { path: { id, assistant_id: assistantId } }
        });
        return true;
      }
    },

    runs: {
      statusCapabilities: {
        /**
         * Fetch canonical Flow run status capability metadata.
         * @throws {EneoError}
         */
        get: async () => {
          return _fetch("/api/v1/flows/runs/status-capabilities/", {
            method: "get"
          });
        }
      },

      /**
       * Create a flow run
       * @param {{
       *  flow: {id: string},
       *  expected_flow_version?: number,
       *  idempotencyKey?: string,
       *  input_payload_json?: any,
       *  step_inputs?: Record<string, {file_ids: string[]}>,
       *  file_ids?: never
       * }} params
       * `step_inputs[stepId].file_ids` is ordered run input. The SDK preserves
       * caller order and leaves duplicate collapse to the API.
       * @throws {EneoError}
       */
      create: async ({
        flow,
        expected_flow_version,
        idempotencyKey,
        input_payload_json,
        step_inputs,
        file_ids
      }) => {
        _rejectTopLevelFileIds(file_ids);
        _rejectReservedInputPayloadKeys(input_payload_json);
        const requestBody = _buildRunRequestBody({
          expected_flow_version,
          input_payload_json,
          step_inputs
        });
        return _fetch("/api/v1/flows/{id}/runs/", {
          method: "post",
          params: {
            path: { id: flow.id },
            header: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined
          },
          requestBody: {
            "application/json": requestBody
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
       *  file_ids?: never
       * }} params
       * `step_inputs[stepId].file_ids` order contributes to the derived key.
       * Reordering the same file ids produces a different key.
       * @returns {Promise<string>}
       */
      deriveUploadIntentIdempotencyKey: async (params) => {
        return _deriveUploadIntentIdempotencyKey(params);
      },

      /**
       * List runs for a flow
       * @param {{flowId: string, limit?: FlowRunListQuery["limit"], offset?: FlowRunListQuery["offset"], status?: FlowRunListQuery["status"]}} params
       * @throws {EneoError}
       */
      list: async ({ flowId, limit = 50, offset = 0, status }) => {
        return _fetch("/api/v1/flows/{id}/runs/", {
          method: "get",
          params: { path: { id: flowId }, query: { limit, offset, status } }
        });
      },

      /**
       * Get a specific flow run
       * @param {{id: string, flowId: string, flow_id?: string}} run
       * @throws {EneoError}
       */
      get: async (run) => {
        const flowId = _requireFlowIdForRunRoute(run, "get");
        return _fetch("/api/v1/flows/{id}/runs/{run_id}/", {
          method: "get",
          params: { path: { id: flowId, run_id: run.id } }
        });
      },

      /**
       * List step outputs for a specific run under a flow.
       * @param {{flowId: string, runId: string}} params
       * @throws {EneoError}
       */
      steps: async ({ flowId, runId }) => {
        return _fetch("/api/v1/flows/{id}/runs/{run_id}/steps/", {
          method: "get",
          params: { path: { id: flowId, run_id: runId } }
        });
      },

      /**
       * Cancel a flow run
       * @param {{id: string, flowId: string, flow_id?: string}} run
       * @throws {EneoError}
       */
      cancel: async (run) => {
        const flowId = _requireFlowIdForRunRoute(run, "cancel");
        return _fetch("/api/v1/flows/{id}/runs/{run_id}/cancel/", {
          method: "post",
          params: { path: { id: flowId, run_id: run.id } }
        });
      },

      /**
       * Rerun one completed step and its downstream dependents.
       * @param {{flowId: string, runId: string, stepId: string} & FlowRunStepRerunRequest} params
       * @returns {Promise<FlowRunStepRerunResponse>}
       * @throws {EneoError}
       */
      rerunStep: async ({ flowId, runId, stepId, ...requestBody }) => {
        return _fetch("/api/v1/flows/{id}/runs/{run_id}/steps/{step_id}/rerun/", {
          method: "post",
          params: { path: { id: flowId, run_id: runId, step_id: stepId } },
          requestBody: { "application/json": requestBody }
        });
      },

      /**
       * Redispatch a stale queued flow run
       * @param {{id: string, flowId: string, flow_id?: string}} run
       * @returns {Promise<import('../types/resources').FlowRunRedispatchResult>}
       * @throws {EneoError}
       */
      redispatch: async (run) => {
        const flowId = _requireFlowIdForRunRoute(run, "redispatch");
        return _fetch("/api/v1/flows/{id}/runs/{run_id}/redispatch/", {
          method: "post",
          params: { path: { id: flowId, run_id: run.id } }
        });
      },

      /**
       * Get evidence for a flow run
       * @param {{id: string, flowId: string, flow_id?: string}} run
       * @throws {EneoError}
       */
      evidence: async (run) => {
        const flowId = _requireFlowIdForRunRoute(run, "evidence");
        return _fetch("/api/v1/flows/{id}/runs/{run_id}/evidence/", {
          method: "get",
          params: { path: { id: flowId, run_id: run.id } }
        });
      },

      /**
       * Export canonical evidence bundle for a flow run.
       * @param {{id: string, flowId: string, flow_id?: string, format?: FlowRunEvidenceExportQuery["format"], detail?: FlowRunEvidenceExportQuery["detail"], reason?: FlowRunEvidenceExportQuery["reason"]}} run
       * @returns {Promise<import('../types/resources').FlowRunEvidenceExport>}
       * @throws {EneoError}
       */
      exportEvidence: async (run) => {
        const flowId = _requireFlowIdForRunRoute(run, "exportEvidence");
        return _fetch("/api/v1/flows/{id}/runs/{run_id}/evidence/export", {
          method: "get",
          params: {
            path: { id: flowId, run_id: run.id },
            query: {
              format: run.format ?? "json",
              detail: run.detail,
              reason: run.reason
            }
          }
        });
      },

      reviewCheckpoints: {
        /**
         * @param {{flowId: string, runId: string}} params
         * @returns {Promise<import('../types/resources').FlowRunReviewCheckpoint | null>}
         */
        active: async ({ flowId, runId }) => {
          return _fetch("/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/active/", {
            method: "get",
            params: { path: { id: flowId, run_id: runId } }
          });
        },

        /**
         * @param {{flowId: string, runId: string, checkpointId: string, expectedCheckpointRevision: number, currentPayloadJson: Record<string, unknown>}} params
         * @returns {Promise<import('../types/resources').FlowRunReviewCheckpoint>}
         */
        edit: async ({
          flowId,
          runId,
          checkpointId,
          expectedCheckpointRevision,
          currentPayloadJson
        }) => {
          return _fetch("/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/", {
            method: "patch",
            params: { path: { id: flowId, run_id: runId, checkpoint_id: checkpointId } },
            requestBody: {
              "application/json": {
                expected_checkpoint_revision: expectedCheckpointRevision,
                current_payload_json: _stableSortObjectKeys(currentPayloadJson)
              }
            }
          });
        },

        /**
         * @param {{flowId: string, runId: string, checkpointId: string, expectedCheckpointRevision: number}} params
         * @returns {Promise<import('../types/resources').FlowRunReviewCheckpoint>}
         */
        approve: async ({ flowId, runId, checkpointId, expectedCheckpointRevision }) => {
          return _fetch(
            "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/approve/",
            {
              method: "post",
              params: { path: { id: flowId, run_id: runId, checkpoint_id: checkpointId } },
              requestBody: {
                "application/json": {
                  expected_checkpoint_revision: expectedCheckpointRevision
                }
              }
            }
          );
        },

        /**
         * @param {{flowId: string, runId: string, checkpointId: string, expectedCheckpointRevision: number, reason: string}} params
         * @returns {Promise<import('../types/resources').FlowRunReviewCheckpoint>}
         */
        reject: async ({ flowId, runId, checkpointId, expectedCheckpointRevision, reason }) => {
          return _fetch(
            "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/reject/",
            {
              method: "post",
              params: { path: { id: flowId, run_id: runId, checkpoint_id: checkpointId } },
              requestBody: {
                "application/json": {
                  expected_checkpoint_revision: expectedCheckpointRevision,
                  reason
                }
              }
            }
          );
        },

        /**
         * @param {{flowId: string, runId: string, checkpointId: string, expectedCheckpointRevision: number, idempotencyKey: string}} params
         * @returns {Promise<import('../types/resources').FlowRunReviewCheckpointResumeResponse>}
         */
        resume: async ({
          flowId,
          runId,
          checkpointId,
          expectedCheckpointRevision,
          idempotencyKey
        }) => {
          return _fetch(
            "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}/resume/",
            {
              method: "post",
              params: {
                path: { id: flowId, run_id: runId, checkpoint_id: checkpointId },
                header: { "Idempotency-Key": idempotencyKey }
              },
              requestBody: {
                "application/json": {
                  expected_checkpoint_revision: expectedCheckpointRevision
                }
              }
            }
          );
        }
      },

      /**
       * Generate signed URL for a flow run artifact download.
       * Uses tenant-scoped access so any user with flow access can download artifacts.
       * @param {{flowId: string, runId: string, fileId: string, expiresIn?: number, contentDisposition?: "attachment" | "inline"}} params
       * @throws {EneoError}
       */
      artifactSignedUrl: async ({
        flowId,
        runId,
        fileId,
        expiresIn = 3600,
        contentDisposition = "attachment"
      }) => {
        return _fetch("/api/v1/flows/{id}/runs/{run_id}/artifacts/{file_id}/signed-url/", {
          method: "post",
          params: { path: { id: flowId, run_id: runId, file_id: fileId } },
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
