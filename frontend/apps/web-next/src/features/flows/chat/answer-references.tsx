import type { ReactNode } from "react";
import {
  referenceComponents as answerReferenceComponents,
  referenceRemarkPlugins as answerReferencePlugins
} from "@/features/references/answer-references";
import { ReferencePillButton, useFlowReferences } from "./reference-pill";
import { answerReference } from "./references";

/**
 * References in a flow chat's answer: every value reference
 * (`{{step_1.output.text}}`) and step mention (`@[Bedömning](step:<id>)`) is
 * drawn as the chat's pill. A mention without the scheme
 * (`@[Bedömning](<id>)`) is the step's pill when the flow has that step, and
 * otherwise its name. Outside FlowReferences, and for anything the flow
 * cannot read as a reference, the text stays as written.
 */

const REFERENCE = /\{\{[^{}\n]+\}\}|@\[[^\]\n]+\]\(step:[^)\s]+\)/g;

/** Stable, so Streamdown keeps one processor for every answer. */
export const referenceRemarkPlugins = answerReferencePlugins(REFERENCE, ["step"]);

function FlowReference({ raw, children }: { raw: string; children?: ReactNode }) {
  const refs = useFlowReferences();
  const part = refs ? answerReference(raw, refs.flow) : null;
  if (!part) return <>{children}</>;
  return part.kind === "text" ? <>{part.text}</> : <ReferencePillButton reference={part} />;
}

/** Pass to <MessageResponse components={referenceComponents}>: references as pills, the rest as the chat draws it. */
export const referenceComponents = answerReferenceComponents(FlowReference);
