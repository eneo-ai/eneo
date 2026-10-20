"use client";

import { useTranslations } from "next-intl";
import { Fragment } from "react";
import type { FlowDefinition } from "./types";

/** One `{{…}}` placeholder of a template, as the definition explains it. */
export type TemplateReference =
  | { kind: "previous" }
  | { kind: "form"; key: string; label: string | null }
  | { kind: "step"; key: string; index: number | null; name: string | null; path: string | null }
  | { kind: "unknown"; raw: string };

export type TemplatePart = { kind: "text"; text: string } | { kind: "ref"; ref: TemplateReference };

const PLACEHOLDER = /\{\{\s*([^{}]+?)\s*\}\}/g;

/** Explains one placeholder's content (`form.key`, `steps.key`, `steps.key.json.a.b`, `previous`). */
export function describeReference(raw: string, definition: FlowDefinition): TemplateReference {
  if (raw === "previous") return { kind: "previous" };
  const [source, key, ...rest] = raw.split(".");
  if (source === "form" && key) {
    const field = definition.form_fields.find((candidate) => candidate.key === key);
    return { kind: "form", key, label: field?.label ?? null };
  }
  if (source === "steps" && key) {
    const index = definition.steps.findIndex((candidate) => candidate.key === key);
    const path = rest[0] === "json" ? rest.slice(1).join(".") || null : rest.join(".") || null;
    return {
      kind: "step",
      key,
      index: index >= 0 ? index : null,
      name: index >= 0 ? (definition.steps[index]?.name ?? null) : null,
      path
    };
  }
  return { kind: "unknown", raw };
}

/** Splits a template into its literal text and its placeholders. */
export function splitTemplate(template: string, definition: FlowDefinition): TemplatePart[] {
  const parts: TemplatePart[] = [];
  let last = 0;
  for (const match of template.matchAll(PLACEHOLDER)) {
    const start = match.index;
    if (start > last) parts.push({ kind: "text", text: template.slice(last, start) });
    parts.push({ kind: "ref", ref: describeReference(match[1]!, definition) });
    last = start + match[0].length;
  }
  if (last < template.length) parts.push({ kind: "text", text: template.slice(last) });
  return parts;
}

type Translate = ReturnType<typeof useTranslations>;

/** The badge text of a reference: "Föregående steg", "Indata · Mötesdatum", "Steg 3 · Sammanfatta · actions". */
export function referenceLabel(ref: TemplateReference, t: Translate): string {
  switch (ref.kind) {
    case "previous":
      return t("flow_ref_previous");
    case "form":
      return `${t("flow_ref_input")} · ${ref.label ?? ref.key}`;
    case "step": {
      const step =
        ref.index !== null
          ? `${t("flow_ref_step", { index: ref.index + 1 })} · ${ref.name ?? ref.key}`
          : `${t("flow_ref_step_unknown")} · ${ref.key}`;
      return ref.path ? `${step} · ${ref.path}` : step;
    }
    case "unknown":
      return ref.raw;
  }
}

/** A `{{…}}` reference as a small badge naming what it reads. */
export function ReferenceBadge({ reference }: { reference: TemplateReference }) {
  const t = useTranslations();
  const unknown = reference.kind === "unknown";
  return (
    <span
      className={
        unknown
          ? "bg-ax-warning-muted text-ax-warning rounded-ax-inner mx-0.5 inline-block px-1 align-baseline font-sans text-[12px] font-medium whitespace-nowrap"
          : "bg-ax-accent-muted text-ax-text-accent rounded-ax-inner mx-0.5 inline-block px-1 align-baseline font-sans text-[12px] font-medium whitespace-nowrap"
      }
    >
      {referenceLabel(reference, t)}
    </span>
  );
}

/**
 * Template text as the author wrote it, with every `{{…}}` shown as a badge
 * that names the step or input it reads; line breaks are kept.
 */
export function TemplateText({
  template,
  definition,
  className
}: {
  template: string;
  definition: FlowDefinition;
  className?: string;
}) {
  const parts = splitTemplate(template, definition);
  return (
    <span className={className}>
      {parts.map((part, index) => (
        <Fragment key={index}>
          {part.kind === "text" ? part.text : <ReferenceBadge reference={part.ref} />}
        </Fragment>
      ))}
    </span>
  );
}
