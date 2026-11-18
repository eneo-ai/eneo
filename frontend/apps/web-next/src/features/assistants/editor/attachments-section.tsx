import { useTranslations } from "use-intl";
import { ResourceAttachmentsSection } from "@/features/files/resource-attachments-section";
import { useAppContext } from "@/components/providers/app-context";
import type { assistantToolModel } from "./effective-config";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

export function AttachmentsSection({
  assistant,
  model
}: {
  assistant: Assistant;
  model: ReturnType<typeof assistantToolModel>;
}) {
  const t = useTranslations();
  const update = useUpdateAssistant(assistant.id);
  const { settings } = useAppContext();

  return (
    <ResourceAttachmentsSection
      attachments={assistant.attachments ?? []}
      allowedAttachments={assistant.allowed_attachments}
      description={t("attachments_description")}
      attachmentMode={{
        fileReferencesEnabled: settings.file_references_enabled === true,
        selectedModel: model
      }}
      onSave={(attachments) => update.mutateAsync({ attachments })}
    />
  );
}
