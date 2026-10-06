"use client";

import { useTranslations } from "next-intl";
import { ResourceAttachmentsSection } from "@/features/files/resource-attachments-section";
import type { App } from "../apps";
import { useUpdateApp } from "./use-app";

export function AttachmentsSection({ app }: { app: App }) {
  const t = useTranslations();
  const update = useUpdateApp(app.id);

  return (
    <ResourceAttachmentsSection
      attachments={app.attachments ?? []}
      allowedAttachments={app.allowed_attachments}
      description={t("app_attachments_description")}
      onSave={(attachments) => update.mutateAsync({ attachments })}
    />
  );
}
