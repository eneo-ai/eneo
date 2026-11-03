import { Button } from "@astryxdesign/core/Button";
import { RadioList, RadioListItem } from "@astryxdesign/core/RadioList";
import { useTranslations } from "use-intl";
import { useAutosaveField } from "@/components/composites/use-autosave";
import { useAppContext } from "@/components/providers/app-context";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

export function MaterialHandling({
  assistant,
  modelSupportsTools
}: {
  assistant: Assistant;
  modelSupportsTools: boolean;
}) {
  const t = useTranslations();
  const { settings } = useAppContext();
  const knowledgeUpdate = useUpdateAssistant(assistant.id);
  const uploadsUpdate = useUpdateAssistant(assistant.id);
  const knowledge = useAutosaveField({
    key: "material-knowledge",
    value: assistant.knowledge_mode,
    save: (knowledge_mode) => knowledgeUpdate.mutateAsync({ knowledge_mode })
  });
  const uploads = useAutosaveField({
    key: "material-uploads",
    value: assistant.inline_file_text,
    save: (inline_file_text) => uploadsUpdate.mutateAsync({ inline_file_text })
  });
  return (
    <div className="flex flex-col gap-6">
      <div id="material-knowledge" className="flex flex-col gap-2">
        <RadioList
          label={t("material_knowledge_timing")}
          description={t("material_knowledge_timing_description")}
          value={knowledge.value}
          onChange={(value) => {
            const next = value === "tool" ? "tool" : "inject";
            knowledge.setValue(next);
            void knowledge.commit(next);
          }}
        >
          <RadioListItem value="tool" label={t("material_when_needed")} />
          <RadioListItem value="inject" label={t("material_before_each_answer")} />
        </RadioList>
        {knowledge.value === "tool" && !modelSupportsTools && (
          <p className="text-warning text-sm">{t("material_knowledge_model_fallback")}</p>
        )}
        {knowledge.dirty && knowledgeUpdate.isError && (
          <Button
            label={t("retry")}
            className="self-start"
            onClick={() => void knowledge.commit()}
          />
        )}
      </div>
      <div id="material-uploads" className="flex flex-col gap-2">
        {settings.file_references_enabled ? (
          <RadioList
            label={t("material_chat_uploads")}
            description={t("material_upload_handling_description")}
            value={uploads.value ? "inline" : "lookup"}
            onChange={(value) => {
              const next = value === "inline";
              uploads.setValue(next);
              void uploads.commit(next);
            }}
          >
            <RadioListItem value="lookup" label={t("material_open_when_needed")} />
            <RadioListItem value="inline" label={t("material_read_directly")} />
          </RadioList>
        ) : (
          <>
            <p className="font-medium">{t("material_chat_uploads")}</p>
            <p className="text-ax-text-secondary text-sm">{t("material_upload_inline_summary")}</p>
          </>
        )}
        {(!settings.file_references_enabled || (!uploads.value && !modelSupportsTools)) && (
          <p className="text-warning text-sm">
            {t(
              settings.file_references_enabled
                ? "material_file_model_fallback"
                : "material_file_references_unavailable"
            )}
          </p>
        )}
        {uploads.dirty && uploadsUpdate.isError && (
          <Button label={t("retry")} className="self-start" onClick={() => void uploads.commit()} />
        )}
      </div>
    </div>
  );
}
