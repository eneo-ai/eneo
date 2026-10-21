"use client";

import { Button } from "@astryxdesign/core/Button";
import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { toastApiError } from "@/lib/api/toast";
import { publishFlow, unpublishFlow } from "./flows";
import { stepsOf, type FlowPublic } from "./types";

/** Publication is a direct, revision-checked action, available without the chat. */
export function FlowPublication({
  flow,
  onSaved
}: {
  flow: FlowPublic;
  onSaved: (flow: FlowPublic) => void;
}) {
  const t = useTranslations();
  const [unpublishing, setUnpublishing] = useState(false);
  const publish = useMutation({
    mutationFn: () => publishFlow(flow),
    onSuccess: (updated) => onSaved(updated),
    onError: (error) => toastApiError(error, t)
  });
  const unpublish = useMutation({
    mutationFn: () => unpublishFlow(flow),
    onSuccess: (updated) => {
      setUnpublishing(false);
      onSaved(updated);
    },
    onError: (error) => toastApiError(error, t)
  });
  const busy = publish.isPending || unpublish.isPending;
  return (
    <>
      <Button
        label={t("flow_publish")}
        size="sm"
        isDisabled={stepsOf(flow.definition).length === 0}
        isLoading={busy}
        isInterruptible
        onClick={() => {
          if (!busy) publish.mutate();
        }}
      />
      {flow.published_version != null && (
        <Button
          label={t("flow_unpublish")}
          size="sm"
          isLoading={busy}
          isInterruptible
          onClick={() => {
            if (!busy) setUnpublishing(true);
          }}
        />
      )}
      <ConfirmDialogControlled
        open={unpublishing}
        onOpenChange={setUnpublishing}
        title={t("flow_unpublish_title")}
        description={t("flow_unpublish_description")}
        confirmLabel={t("flow_unpublish")}
        pending={unpublish.isPending}
        onConfirm={() => unpublish.mutate()}
      />
    </>
  );
}
