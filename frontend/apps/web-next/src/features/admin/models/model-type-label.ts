import { useTranslations } from "next-intl";
import type { ModelKind } from "./models";

/** Translated model type for UI labels ("Chatt", "Inbäddning", "Transkription"). */
export function useModelTypeLabel() {
  const t = useTranslations();
  return (kind: ModelKind) =>
    kind === "completion"
      ? t("admin_model_type_completion")
      : kind === "embedding"
        ? t("admin_model_type_embedding")
        : t("admin_model_type_transcription");
}
