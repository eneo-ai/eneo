"use client";

import { useTranslations } from "use-intl";
import type { FlowPublic } from "../editor/step-types";
import {
  referenceLabel,
  ReferencePill,
  ReferencePillButton,
  useFlowReferences
} from "./reference-pill";
import { referenceParts } from "./references";

type Flow = Pick<FlowPublic, "steps" | "metadata_json">;

/**
 * Text that holds references as the flow chat writes them (`@[Name](step:<id>)`,
 * `{{step_1.output.text}}`), with each reference as the chat's pill: a
 * button that opens the one reference card of the page (`interactive`
 * false: the pill alone, as in a dialog, where the card cannot open).
 * Outside FlowReferences the text shows as written.
 */
export function ReferenceText({
  text,
  interactive = true
}: {
  text: string;
  interactive?: boolean;
}) {
  const refs = useFlowReferences();
  if (!refs) return <>{text}</>;
  return (
    <>
      {referenceParts(text, refs.flow).map((part, index) =>
        part.kind === "text" ? (
          <span key={index}>{part.text}</span>
        ) : interactive ? (
          <ReferencePillButton key={index} reference={part} />
        ) : (
          <ReferencePill key={index} reference={part} />
        )
      )}
    </>
  );
}

/** The same text in words, each reference as its pill says it: for an accessible name. */
export function referencePlainText(
  text: string,
  flow: Flow,
  t: ReturnType<typeof useTranslations>
): string {
  return referenceParts(text, flow)
    .map((part) => (part.kind === "text" ? part.text : referenceLabel(part, flow, t)))
    .join("");
}
