"use client";

import { useTranslations } from "next-intl";
import { ResourceAttachmentsSection } from "@/features/files/resource-attachments-section";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

export function AttachmentsSection({ assistant }: { assistant: Assistant }) {
  const t = useTranslations();
  const update = useUpdateAssistant(assistant.id);

  return (
    <ResourceAttachmentsSection
      attachments={assistant.attachments ?? []}
      allowedAttachments={assistant.allowed_attachments}
      description={t("attachments_description")}
      onSave={(attachments) => update.mutateAsync({ attachments })}
    />
  );
}
