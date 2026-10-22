"use client";

import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useRef } from "react";
import { browserApi } from "@/lib/api/browser";
import { flowKeys } from "../flows-api";
import { flowEditorKeys } from "./editor-api";
import { readTemplateFill } from "./step-configs";
import type { FlowAssistant, FlowPublic } from "./step-types";

/**
 * Files uploaded inside one step edit: attachments of the step assistant
 * (`POST /files/`) and Word templates of the flow (`POST
 * /flows/{id}/template-files/`). An edit that is cancelled, or closed
 * without saving, releases those its saved flow does not reference, through
 * the endpoints that delete them; a file the saved flow references is never
 * released.
 */

export type EditorUpload = { kind: "file" | "template"; id: string };

const RecordUploadContext = createContext<(upload: EditorUpload) => void>(() => {});

export const RecordUploadProvider = RecordUploadContext.Provider;

/** Called by a field that uploaded a file, so the edit can release it if it is dropped. */
export function useRecordUpload(): (upload: EditorUpload) => void {
  return useContext(RecordUploadContext);
}

/** The uploads the saved flow and step assistant do not reference: these may go. */
export function releasableUploads(
  uploads: readonly EditorUpload[],
  saved: { flows: readonly (FlowPublic | undefined)[]; assistant: FlowAssistant | undefined }
): EditorUpload[] {
  const templates = new Set(
    saved.flows.flatMap((flow) =>
      (flow?.steps ?? []).flatMap((step) => {
        const id = readTemplateFill(step.output_config).templateAssetId;
        return id ? [id] : [];
      })
    )
  );
  const files = new Set((saved.assistant?.attachments ?? []).map((file) => file.id));
  return uploads.filter((upload) =>
    upload.kind === "template" ? !templates.has(upload.id) : !files.has(upload.id)
  );
}

/**
 * The uploads of one step edit. `record` notes an upload; `keepSaved` forgets
 * those a save now references; `release` deletes the rest. The edit's end
 * (it unmounts) releases what is still noted, so closing it without saving
 * cleans up as cancelling does.
 */
export function useEditorUploads(flow: FlowPublic, assistantId: string) {
  const queryClient = useQueryClient();
  const uploads = useRef<EditorUpload[]>([]);
  // The flow the edit last saved or read; set from events, read when releasing.
  const savedFlow = useRef(flow);
  const flowId = flow.id;

  const savedState = useCallback(
    () => ({
      flows: [savedFlow.current, queryClient.getQueryData<FlowPublic>(flowKeys.flow(flowId))],
      assistant: queryClient.getQueryData<FlowAssistant>(
        flowEditorKeys.assistant(flowId, assistantId)
      )
    }),
    [assistantId, flowId, queryClient]
  );

  const record = useCallback((upload: EditorUpload) => {
    uploads.current = [...uploads.current, upload];
  }, []);

  const keepSaved = useCallback(
    (saved: FlowPublic) => {
      savedFlow.current = saved;
      const releasable = releasableUploads(uploads.current, savedState());
      uploads.current = uploads.current.filter((upload) => releasable.includes(upload));
    },
    [savedState]
  );

  const release = useCallback(() => {
    const dropped = releasableUploads(uploads.current, savedState());
    uploads.current = [];
    for (const upload of dropped) {
      // Best effort, and never in the way of closing: the core keeps a file
      // anything still uses.
      const remove = async () => {
        if (upload.kind === "file") {
          await browserApi.DELETE("/api/v1/files/{id}/", { params: { path: { id: upload.id } } });
          return;
        }
        await browserApi.DELETE("/api/v1/flows/{id}/template-files/{file_id}/", {
          params: { path: { id: flowId, file_id: upload.id } }
        });
        await queryClient.invalidateQueries({ queryKey: flowEditorKeys.templateFiles(flowId) });
      };
      remove().catch(() => undefined);
    }
  }, [flowId, queryClient, savedState]);

  useEffect(() => () => release(), [release]);

  return { record, keepSaved, release };
}
