"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent } from "@astryxdesign/core/Layout";
import { ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Chip } from "./flow-fields";
import { stepKindLabel } from "./flow-labels";
import { FlowStepDetails, stepSummary, type FlowNames } from "./flow-step-card";
import { formFieldsOf, stepsOf, type FlowPublic, type FormFieldType } from "./types";

const FIELD_TYPE_KEYS: Record<FormFieldType, string> = {
  text: "flow_field_type_text",
  number: "flow_field_type_number",
  select: "flow_field_type_select",
  file: "flow_field_type_file",
  audio: "flow_field_type_audio"
};

/** "Publicerad v3" / "Utkast", and whether the draft has moved on since. */
export function FlowStatusBadges({
  flow
}: {
  flow: Pick<FlowPublic, "published_version" | "has_unpublished_changes">;
}) {
  const t = useTranslations();
  const published = flow.published_version != null;
  return (
    <>
      <Badge
        variant={published ? "success" : "neutral"}
        label={
          published
            ? t("flow_status_published", { version: flow.published_version! })
            : t("flow_status_draft")
        }
      />
      {published && flow.has_unpublished_changes && (
        <Badge variant="warning" label={t("flow_status_unpublished_changes")} />
      )}
    </>
  );
}

/**
 * A flow as it is defined: description and status, the inputs a run asks
 * for, then the steps as a compact list. A step opens in a dialog with
 * every parameter visible. Read-only throughout.
 */
export function FlowDefinition({ flow, names = {} }: { flow: FlowPublic; names?: FlowNames }) {
  const t = useTranslations();
  const { definition } = flow;
  const fields = formFieldsOf(definition);
  const steps = stepsOf(definition);
  const [openIndex, setOpenIndex] = useState<number | null>(null);
  const openStep = openIndex !== null ? (steps[openIndex] ?? null) : null;
  const close = () => setOpenIndex(null);

  return (
    <div className="flex flex-col gap-5 p-4">
      <section aria-label={t("flow_section_about")} className="flex flex-col gap-2">
        {flow.description ? (
          <p className="text-ax-text-secondary m-0 text-[13px] leading-snug">{flow.description}</p>
        ) : null}
        <div className="flex flex-wrap items-center gap-1.5">
          <FlowStatusBadges flow={flow} />
          <Chip>{t("flow_steps_count", { count: steps.length })}</Chip>
        </div>
      </section>

      <section aria-labelledby="flow-inputs-heading" className="flex flex-col gap-2">
        <h3
          id="flow-inputs-heading"
          className="text-ax-text-secondary m-0 text-[11px] font-semibold tracking-wide uppercase"
        >
          {t("flow_section_inputs")}
        </h3>
        {fields.length === 0 ? (
          <p className="text-ax-text-secondary m-0 text-[13px]">{t("flow_inputs_none")}</p>
        ) : (
          <ul className="m-0 flex list-none flex-col gap-1 p-0">
            {fields.map((field) => (
              <li
                key={field.key}
                className="border-ax-border flex flex-col gap-0.5 border-b py-1.5 text-[13px] last:border-b-0"
              >
                <span className="font-medium">{field.label}</span>
                {field.description && (
                  <span className="text-ax-text-secondary text-xs">{field.description}</span>
                )}
                <span className="text-ax-text-secondary text-xs">
                  {t(FIELD_TYPE_KEYS[field.type] ?? "flow_field_type_text")}
                  {" · "}
                  {field.required === false ? t("optional") : t("required")}
                  {field.type === "select" && field.options?.length
                    ? ` · ${field.options.join(", ")}`
                    : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="flow-steps-heading" className="flex flex-col gap-2">
        <h3
          id="flow-steps-heading"
          className="text-ax-text-secondary m-0 text-[11px] font-semibold tracking-wide uppercase"
        >
          {t("flow_section_steps")}
        </h3>
        {steps.length === 0 ? (
          <p className="text-ax-text-secondary m-0 text-[13px]">{t("flow_steps_none")}</p>
        ) : (
          <ol className="m-0 flex list-none flex-col gap-1.5 p-0">
            {steps.map((step, index) => (
              <li key={step.id ?? step.key}>
                <button
                  type="button"
                  aria-haspopup="dialog"
                  aria-label={t("flow_step_open", { index: index + 1, name: step.name })}
                  onClick={() => setOpenIndex(index)}
                  className="border-ax-border bg-ax-card rounded-ax-container hover:bg-ax-hover focus-visible:outline-ring flex min-h-11 w-full items-center gap-2.5 border px-3 py-2 text-left focus-visible:outline-2 focus-visible:outline-offset-2"
                >
                  <span
                    aria-hidden="true"
                    className="bg-ax-muted text-ax-text-secondary flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold tabular-nums"
                  >
                    {index + 1}
                  </span>
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate text-sm font-semibold">{step.name}</span>
                    <span className="text-ax-text-secondary truncate text-xs">
                      {stepSummary(step, names, t)}
                    </span>
                  </span>
                  <Badge variant="neutral" label={stepKindLabel(step.kind, t)} />
                  <ChevronRight
                    aria-hidden="true"
                    className="text-ax-text-tertiary size-4 shrink-0"
                  />
                </button>
              </li>
            ))}
          </ol>
        )}
      </section>

      <Dialog
        isOpen={openStep !== null}
        onOpenChange={(open) => !open && close()}
        width={560}
        maxHeight="85dvh"
      >
        {openStep && openIndex !== null && (
          <Layout
            header={
              <DialogHeader
                title={openStep.name}
                subtitle={t("flow_step_dialog_subtitle", {
                  index: openIndex + 1,
                  count: steps.length,
                  kind: stepKindLabel(openStep.kind, t)
                })}
                onOpenChange={(open) => !open && close()}
              />
            }
            content={
              <LayoutContent>
                <FlowStepDetails step={openStep} definition={definition} names={names} />
              </LayoutContent>
            }
          />
        )}
      </Dialog>
    </div>
  );
}
