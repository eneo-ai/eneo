"use client";

import type { ComponentProps } from "react";
import type { MessageResponseProps } from "@/components/ai-elements/message";
import { AnswerLink } from "@/features/chat/answer-links";
import { ReferencePillButton, useFlowReferences } from "./reference-pill";
import { parseReference } from "./references";

/**
 * References in an answer. A remark plugin turns every value reference
 * (`{{step_1.output.text}}`) and step mention (`@[Bedömning](step:<id>)`)
 * in the answer's text into a link node whose target carries the reference
 * as written, and the `a` component draws exactly those as pills. Code keeps
 * its text as it is, so copying a code block still gives the real template.
 * Every other link goes on to the chat's own link (document names and
 * citations).
 */

const PREFIX = "#eneo-ref-";
const REFERENCE = /\{\{[^{}\n]+\}\}|@\[[^\]\n]+\]\(step:[^)\s]+\)/g;

type MdNode = { type: string; value?: string; url?: string; children?: MdNode[] };

function splitReferences(value: string): MdNode[] {
  const out: MdNode[] = [];
  let cursor = 0;
  for (const match of value.matchAll(REFERENCE)) {
    const start = match.index ?? 0;
    if (start > cursor) out.push({ type: "text", value: value.slice(cursor, start) });
    out.push(referenceLink(match[0]));
    cursor = start + match[0].length;
  }
  if (out.length === 0) return [{ type: "text", value }];
  if (cursor < value.length) out.push({ type: "text", value: value.slice(cursor) });
  return out;
}

function isOneReference(value: string): boolean {
  const trimmed = value.trim();
  const match = trimmed.match(REFERENCE);
  return match?.length === 1 && match[0] === trimmed;
}

function textOf(node: MdNode): string {
  if (node.type === "text") return node.value ?? "";
  return (node.children ?? []).map(textOf).join("");
}

function referenceLink(raw: string): MdNode {
  return {
    type: "link",
    url: PREFIX + encodeURIComponent(raw),
    children: [{ type: "text", value: raw }]
  };
}

function transform(node: MdNode) {
  if (!node.children) return;
  const next: MdNode[] = [];
  for (const child of node.children) {
    // Markdown reads a mention as "@" and a link to `step:<id>`: put them back together.
    const before = next.at(-1);
    if (
      child.type === "link" &&
      child.url?.startsWith("step:") &&
      before?.type === "text" &&
      before.value?.endsWith("@")
    ) {
      before.value = before.value.slice(0, -1);
      if (!before.value) next.pop();
      next.push(referenceLink(`@[${textOf(child)}](${child.url})`));
      continue;
    }
    if (child.type === "text" && child.value) {
      next.push(...splitReferences(child.value));
    } else if (child.type === "inlineCode" && isOneReference(child.value ?? "")) {
      // A reference the answer put in backticks is still the reference.
      next.push(referenceLink(child.value!.trim()));
    } else {
      if (child.type !== "code" && child.type !== "inlineCode" && child.type !== "link") {
        transform(child);
      }
      next.push(child);
    }
  }
  node.children = next;
}

function referencesRemark() {
  return (tree: MdNode) => transform(tree);
}

/** Stable, so Streamdown keeps one processor for every answer. */
export const referenceRemarkPlugins: NonNullable<MessageResponseProps["remarkPlugins"]> = [
  referencesRemark
];

function ReferenceLink(props: ComponentProps<"a"> & { node?: unknown }) {
  const refs = useFlowReferences();
  const href = typeof props.href === "string" ? props.href : "";
  if (href.startsWith(PREFIX)) {
    const reference = refs
      ? parseReference(decodeURIComponent(href.slice(PREFIX.length)), refs.flow)
      : null;
    return reference ? <ReferencePillButton reference={reference} /> : <>{props.children}</>;
  }
  return <AnswerLink {...props} />;
}

/** Pass to <MessageResponse components={referenceComponents}>: references as pills, the rest as the chat draws it. */
export const referenceComponents: NonNullable<MessageResponseProps["components"]> = {
  a: ReferenceLink
};
