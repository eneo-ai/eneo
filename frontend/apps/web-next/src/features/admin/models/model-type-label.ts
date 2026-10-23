import { useTranslations } from "next-intl";
import type { ModelKind } from "./models";

/** Translated model type for UI labels ("Chatt", "Inbäddning", "Transkription", "Bildgenerering"). */
export function useModelTypeLabel() {
  const t = useTranslations();
  return (kind: ModelKind) => {
    switch (kind) {
      case "completion":
        return t("admin_model_type_completion");
      case "embedding":
        return t("admin_model_type_embedding");
      case "transcription":
        return t("admin_model_type_transcription");
      case "image":
        return t("admin_model_type_image");
    }
  };
}
