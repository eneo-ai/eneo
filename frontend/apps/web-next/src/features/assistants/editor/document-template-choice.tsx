"use client";

import { Collapsible } from "@astryxdesign/core/Collapsible";
import { RadioList, RadioListItem } from "@astryxdesign/core/RadioList";
import { Selector } from "@astryxdesign/core/Selector";
import { blockingError, ListError, RefreshError } from "@/components/composites/query-state";
import { LoadingState } from "@/components/composites/loading-state";
import { useAutosave } from "@/components/composites/use-autosave";
import type { Schema } from "@/lib/api/models";
import { useRef, useState } from "react";
import { useFocusRescue } from "@/lib/focus-rescue";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { availableDocumentTemplatesQueryOptions } from "@/features/document-templates/document-templates";
import { browserApi } from "@/lib/api/browser";
import { useUpdateAssistant, type Assistant } from "./use-assistant";

type Choice = Schema<"DocumentTemplateChoicePublic">;

/** The template followed by this assistant's Word and PDF output. */
export function AssistantDocumentTemplateChoice({
  assistant,
  isDisabled = false
}: {
  assistant: Assistant;
  isDisabled?: boolean;
}) {
  const t = useTranslations();
  const container = useRef<HTMLDivElement>(null);
  const statusTarget = useRef<HTMLParagraphElement>(null);
  const rescue = useFocusRescue();
  // Keep a failed save's retry control mounted while the next attempt runs.
  const [saveError, setSaveError] = useState<unknown>(null);
  const templates = useQuery(availableDocumentTemplatesQueryOptions(browserApi));
  const update = useUpdateAssistant(assistant.id);
  const autosave = useAutosave("assistant-document-template");
  const editable = assistant.permissions?.includes("edit") ?? false;
  const busy = isDisabled || update.isPending;
  const attemptedChoice = update.variables?.document_template;
  const choice =
    editable && (update.isPending || update.isError)
      ? (attemptedChoice ?? assistant.document_template)
      : assistant.document_template;
  const options = templates.data?.items;
  const selected = options?.find((template) => template.id === choice?.template_id);
  const defaultName =
    options?.find((template) => template.is_default)?.name ?? t("document_template_builtin_name");
  const status =
    choice?.mode === "builtin"
      ? t("document_template_status", { name: t("document_template_builtin_name") })
      : choice?.mode === "selected" && selected
        ? t("document_template_status", { name: selected.name })
        : options
          ? t("document_template_status_default", { name: defaultName })
          : t("document_template_status", {
              name: t(
                choice?.mode === "selected"
                  ? "document_template_choice_selected"
                  : "document_template_choice_default"
              )
            });
  async function retryTemplates() {
    const result = await templates.refetch();
    if (!result.isError) rescue(statusTarget.current);
    return result;
  }
  function save(value: Choice) {
    if (!editable || busy) return;
    void autosave(async () => {
      try {
        await update.mutateAsync({ document_template: value });
        setSaveError(null);
        rescue(
          container.current?.querySelector<HTMLButtonElement>(".astryx-collapsible-trigger") ?? null
        );
      } catch (error) {
        setSaveError(error);
        throw error;
      }
    });
  }
  function setMode(mode: string) {
    if (mode === "selected") {
      const target = selected ?? options?.find((template) => template.is_default) ?? options?.[0];
      if (target) save({ mode, template_id: target.id });
    } else if (mode === "default" || mode === "builtin") save({ mode, template_id: null });
  }
  return (
    <div
      id="assistant-document-template"
      ref={container}
      className="ms-8 mt-2"
      aria-busy={busy || undefined}
    >
      <p ref={statusTarget} tabIndex={-1} className="text-ax-text-secondary text-sm">
        {status}
      </p>
      {blockingError(templates) ? (
        <ListError
          error={templates.error}
          isRetrying={templates.isFetching}
          onRetry={() => void retryTemplates()}
        />
      ) : templates.isPending ? (
        <LoadingState variant="text" rows={1} />
      ) : (
        <RefreshError queries={[{ ...templates, refetch: retryTemplates }]} />
      )}
      {saveError != null && (
        <ListError
          error={saveError}
          title={t("save_failed")}
          isRetrying={busy}
          onRetry={editable && attemptedChoice ? () => save(attemptedChoice) : undefined}
        />
      )}
      {editable ? (
        <Collapsible trigger={t("document_template_change")} defaultIsOpen={false}>
          <div className="bg-ax-sunken rounded-ax-inner p-3">
            <RadioList
              label={t("document_template_choice_label")}
              value={choice?.mode ?? "default"}
              onChange={setMode}
              isDisabled={busy}
              disabledMessage={t("saving")}
              size="sm"
            >
              <RadioListItem
                value="default"
                label={t("document_template_choice_default")}
                description={options ? defaultName : undefined}
              />
              <RadioListItem
                value="selected"
                label={t("document_template_choice_selected")}
                isDisabled={!options?.length}
              />
              <RadioListItem value="builtin" label={t("document_template_choice_builtin")} />
            </RadioList>
            {choice?.mode === "selected" && options && options.length > 0 && (
              <Selector
                label={t("document_template_choice_selected")}
                value={choice.template_id ?? ""}
                options={options.map((template) => ({ value: template.id, label: template.name }))}
                onChange={(template_id) => save({ mode: "selected", template_id })}
                isDisabled={busy}
                disabledMessage={t("saving")}
                size="sm"
                width="100%"
              />
            )}
            {options?.length === 0 && (
              <p className="text-ax-text-secondary mt-2 text-xs">
                {t("document_template_choice_none_available")}
              </p>
            )}
            <p className="text-ax-text-secondary mt-2 text-sm">
              {t("document_template_choice_help")}
            </p>
          </div>
        </Collapsible>
      ) : (
        <p className="text-ax-text-secondary mt-1 text-xs">
          {t("document_template_choice_read_only")}
        </p>
      )}
    </div>
  );
}
