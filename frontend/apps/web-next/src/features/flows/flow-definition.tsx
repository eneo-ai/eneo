"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { useTranslations } from "next-intl";
import { Chip } from "./flow-fields";
import { FlowStepCard, type FlowNames } from "./flow-step-card";
import type { FlowPublic, FormFieldType } from "./types";

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
 * for, then every step with all of its parameters. Read-only throughout.
 */
export function FlowDefinition({ flow, names }: { flow: FlowPublic; names?: FlowNames }) {
  const t = useTranslations();
  const { definition } = flow;
  return (
    <div className="flex flex-col gap-5 p-4">
      <section aria-label={t("flow_section_about")} className="flex flex-col gap-2">
        {flow.description ? (
          <p className="text-ax-text-secondary m-0 text-[13px] leading-snug">{flow.description}</p>
        ) : null}
        <div className="flex flex-wrap items-center gap-1.5">
          <FlowStatusBadges flow={flow} />
          <Chip>{t("flow_steps_count", { count: definition.steps.length })}</Chip>
        </div>
      </section>

      <section aria-labelledby="flow-inputs-heading" className="flex flex-col gap-2">
        <h3
          id="flow-inputs-heading"
          className="text-ax-text-secondary m-0 text-[11px] font-semibold tracking-wide uppercase"
        >
          {t("flow_section_inputs")}
        </h3>
        {definition.form_fields.length === 0 ? (
          <p className="text-ax-text-secondary m-0 text-[13px]">{t("flow_inputs_none")}</p>
        ) : (
          <ul className="m-0 flex list-none flex-col gap-1 p-0">
            {definition.form_fields.map((field) => (
              <li
                key={field.key}
                className="border-ax-border flex items-baseline justify-between gap-3 border-b py-1 text-[13px] last:border-b-0"
              >
                <span className="min-w-0">
                  <span className="font-medium">{field.label}</span>
                  {field.description && (
                    <span className="text-ax-text-secondary block text-xs">
                      {field.description}
                    </span>
                  )}
                </span>
                <span className="text-ax-text-secondary shrink-0 text-xs">
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
        {definition.steps.length === 0 ? (
          <p className="text-ax-text-secondary m-0 text-[13px]">{t("flow_steps_none")}</p>
        ) : (
          <ol className="m-0 flex list-none flex-col gap-2 p-0">
            {definition.steps.map((step, index) => (
              <li key={step.id ?? step.key}>
                <FlowStepCard step={step} index={index} definition={definition} names={names} />
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}
