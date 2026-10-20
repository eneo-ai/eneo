"use client";

import { Button } from "@astryxdesign/core/Button";
import { TextArea } from "@astryxdesign/core/TextArea";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toastApiError } from "@/lib/api/toast";
import { ClientTime } from "@/components/composites/client-time";
import { approveCheckpointAndContinue, editCheckpoint, flowKeys, rejectCheckpoint } from "./flows";
import type { FlowRunReviewCheckpointPublic } from "./types";

/** The reviewed output as editable text: the text itself, or the JSON value pretty-printed. */
export function checkpointText(checkpoint: FlowRunReviewCheckpointPublic): string {
  const payload = checkpoint.current_payload_json ?? checkpoint.original_payload_json ?? {};
  if (checkpoint.output_type === "json") {
    return JSON.stringify("value" in payload ? payload.value : payload, null, 2);
  }
  const text = payload.text;
  return typeof text === "string" ? text : JSON.stringify(payload, null, 2);
}

/**
 * The decision on a paused run: approve as it is, save an edit and approve,
 * or reject. Every action is an explicit button; nothing is sent by typing.
 * One action runs at a time: the running one shows progress and keeps the
 * focus, and a press on any of them is ignored until it has finished.
 */
export function FlowReviewActions({
  flowId,
  runId,
  checkpoint
}: {
  flowId: string;
  runId: string;
  checkpoint: FlowRunReviewCheckpointPublic;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const editable = checkpoint.review_mode === "edit";
  const original = checkpoint.state === "awaiting_review" || checkpoint.state === "edited";
  const [text, setText] = useState(() => checkpointText(checkpoint));
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const changed = editable && text !== checkpointText(checkpoint);
  const ref = { flowId, runId, checkpointId: checkpoint.id, revision: checkpoint.revision };

  const refresh = () => queryClient.invalidateQueries({ queryKey: flowKeys.run(flowId, runId) });
  const onError = (error: unknown) => {
    toastApiError(error, t);
    void refresh();
  };

  const approve = useMutation({
    mutationFn: () => approveCheckpointAndContinue(ref),
    onSuccess: refresh,
    onError
  });
  const saveAndApprove = useMutation({
    mutationFn: async () => {
      const payload = editedPayload();
      const edited = await editCheckpoint(ref, payload);
      return approveCheckpointAndContinue({ ...ref, revision: edited.revision });
    },
    onSuccess: refresh,
    onError
  });
  const reject = useMutation({
    mutationFn: () => rejectCheckpoint(ref, reason.trim() || null),
    onSuccess: refresh,
    onError
  });
  const busy = approve.isPending || saveAndApprove.isPending || reject.isPending;

  /** The edited text as the checkpoint stores it; JSON must parse. */
  function editedPayload(): Record<string, unknown> {
    if (checkpoint.output_type === "json") return { value: JSON.parse(text) as unknown };
    return { text };
  }

  function submitEdit() {
    if (busy) return;
    if (checkpoint.output_type === "json") {
      try {
        JSON.parse(text);
      } catch {
        setProblem(t("flow_review_invalid_json"));
        return;
      }
    }
    setProblem(null);
    saveAndApprove.mutate();
  }

  if (!original) return null;

  return (
    <div className="border-ax-warning bg-ax-warning-muted rounded-ax-container flex flex-col gap-3 border p-3">
      <div className="flex flex-col gap-0.5">
        <p className="text-ax-text m-0 text-[13px] font-semibold">{t("flow_review_title")}</p>
        <p className="text-ax-text-secondary m-0 text-xs">
          {editable ? t("flow_review_hint_edit") : t("flow_review_hint_view")}
          {checkpoint.expires_at && (
            <>
              {" · "}
              {t("flow_review_expires")} <ClientTime value={checkpoint.expires_at} format="auto" />
            </>
          )}
        </p>
      </div>
      {editable ? (
        <TextArea
          label={t("flow_review_text_label")}
          value={text}
          onChange={(value) => {
            setText(value);
            if (problem) setProblem(null);
          }}
          rows={10}
          size="sm"
          isDisabled={busy}
          status={problem ? { type: "error", message: problem } : undefined}
        />
      ) : (
        <pre className="bg-ax-surface rounded-ax-inner m-0 max-h-80 overflow-auto p-2.5 font-mono text-[12.5px] whitespace-pre-wrap">
          {text}
        </pre>
      )}
      <TextArea
        label={t("flow_review_reason_label")}
        description={t("flow_review_reason_hint")}
        value={reason}
        onChange={setReason}
        rows={2}
        size="sm"
        isDisabled={busy}
      />
      <div className="flex flex-wrap gap-2">
        <Button
          label={t("flow_review_approve")}
          variant="primary"
          size="sm"
          isLoading={approve.isPending}
          isInterruptible
          onClick={() => {
            if (!busy) approve.mutate();
          }}
        />
        {editable && (
          <Button
            label={t("flow_review_save_and_approve")}
            size="sm"
            isLoading={saveAndApprove.isPending}
            isInterruptible
            isDisabled={!changed}
            onClick={submitEdit}
          />
        )}
        <Button
          label={t("flow_review_reject")}
          variant="destructive"
          size="sm"
          isLoading={reject.isPending}
          isInterruptible
          onClick={() => {
            if (!busy) reject.mutate();
          }}
        />
      </div>
    </div>
  );
}
