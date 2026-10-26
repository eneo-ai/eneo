"use client";

import { Selector } from "@astryxdesign/core/Selector";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { SettingsRow } from "@/components/composites/settings-rows";
import { useAutosave } from "@/components/composites/use-autosave";
import { useSpace } from "@/features/spaces/use-space";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

const NO_RERANKER = "none";

/**
 * The rerank model that orders what the assistant's knowledge search finds.
 * Only models the space allows are offered (the backend refuses others); a
 * saved choice that is no longer allowed stays visible until it is changed.
 */
export function RerankerRow({ assistant }: { assistant: Assistant }) {
  const t = useTranslations();
  const { space } = useSpace();
  const update = useUpdateAssistant(assistant.id);
  const autosave = useAutosave("knowledge");
  const { data: models } = useQuery({
    queryKey: ["ai-models", space.id],
    queryFn: () =>
      unwrap(browserApi.GET("/api/v1/ai-models/", { params: { query: { space_id: space.id } } }))
  });

  const saved = assistant.rerank_model_id ?? null;
  const [choice, setChoice] = useState<string | null>(saved);
  // Adopt server changes (e.g. our own save landing) unless the user diverged.
  const savedRef = useRef(saved);
  useEffect(() => {
    if (savedRef.current === saved) return;
    const previous = savedRef.current;
    savedRef.current = saved;
    setChoice((current) => (current === previous ? saved : current));
  }, [saved]);

  const selectable = (models?.rerank_models ?? []).filter(
    (model) => model.can_access && model.meets_security_classification !== false
  );
  const unavailable =
    models !== undefined && choice !== null && !selectable.some((model) => model.id === choice);
  if (selectable.length === 0 && choice === null && saved === null) return null;

  function handleChange(value: string) {
    const next = value === NO_RERANKER ? null : value;
    const previous = choice;
    setChoice(next);
    void autosave(() => update.mutateAsync({ rerank_model_id: next })).then((result) => {
      if (result !== undefined) return;
      setChoice((current) => (current === next ? previous : current));
    });
  }

  return (
    <SettingsRow title={t("material_reranker")} description={t("material_reranker_description")}>
      <Selector
        label={t("material_reranker")}
        isLabelHidden
        value={choice ?? NO_RERANKER}
        onChange={handleChange}
        options={[
          { value: NO_RERANKER, label: t("material_reranker_none") },
          ...selectable.map((model) => ({ value: model.id, label: model.nickname ?? model.name })),
          // The saved choice keeps its own value, so picking another is a real change.
          ...(unavailable ? [{ value: choice, label: t("material_reranker_missing") }] : [])
        ]}
      />
      {unavailable && (
        <p className="border-warning/30 bg-warning/10 text-warning rounded-md border px-3 py-2 text-sm">
          {t("material_reranker_unavailable")}
        </p>
      )}
    </SettingsRow>
  );
}
