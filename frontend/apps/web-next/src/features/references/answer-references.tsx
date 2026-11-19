import type { ComponentProps, ComponentType, ReactNode } from "react";
import type { MessageResponseProps } from "@/components/ai-elements/message";
import { AnswerLink } from "@/features/chat/answer-links";
import { parseBareMention } from "./mentions";

/**
 * References in an answer. A remark plugin turns every reference a page
 * recognises in the answer's text into a link node whose target carries the
 * reference as written, and the page's `a` component draws exactly those
 * (as pills). Code keeps its text as it is, so copying a code block still
 * gives the reference as written. Every other link goes on to the chat's own
 * link (document names and citations).
 */

const PREFIX = "#eneo-ref-";

type MdNode = { type: string; value?: string; url?: string; children?: MdNode[] };
type Plugins = NonNullable<MessageResponseProps["remarkPlugins"]>;
type Components = NonNullable<MessageResponseProps["components"]>;

function referenceLink(raw: string): MdNode {
  return {
    type: "link",
    url: PREFIX + encodeURIComponent(raw),
    children: [{ type: "text", value: raw }]
  };
}

function textOf(node: MdNode): string {
  if (node.type === "text") return node.value ?? "";
  return (node.children ?? []).map(textOf).join("");
}

/**
 * A remark plugin for the references `pattern` matches (a global pattern).
 * Markdown reads a mention (`@[Name](step:<id>)`) as "@" and a link to
 * `step:<id>`: for each of `mentionSchemes` the two are put back together.
 * So are "@" and a link to an address no link can go to (`@[Namn](name)`),
 * a mention a model wrote without the scheme: the page's reference says what
 * it names, and it never reaches the link sanitiser. "@" before a link to a
 * web address, and a link without "@", stay links.
 */
export function referenceRemarkPlugins(
  pattern: RegExp,
  mentionSchemes: readonly string[]
): Plugins {
  const prefixes = mentionSchemes.map((scheme) => `${scheme}:`);

  const split = (value: string): MdNode[] => {
    const out: MdNode[] = [];
    let cursor = 0;
    for (const match of value.matchAll(pattern)) {
      const start = match.index ?? 0;
      if (start > cursor) out.push({ type: "text", value: value.slice(cursor, start) });
      out.push(referenceLink(match[0]));
      cursor = start + match[0].length;
    }
    if (out.length === 0) return [{ type: "text", value }];
    if (cursor < value.length) out.push({ type: "text", value: value.slice(cursor) });
    return out;
  };

  const isOne = (value: string) => {
    const trimmed = value.trim();
    const match = trimmed.match(pattern);
    return match?.length === 1 && match[0] === trimmed;
  };

  const transform = (node: MdNode) => {
    if (!node.children) return;
    const next: MdNode[] = [];
    for (const child of node.children) {
      const before = next.at(-1);
      if (child.type === "link" && before?.type === "text" && before.value?.endsWith("@")) {
        const raw = `@[${textOf(child)}](${child.url})`;
        if (prefixes.some((prefix) => child.url?.startsWith(prefix)) || parseBareMention(raw)) {
          before.value = before.value.slice(0, -1);
          if (!before.value) next.pop();
          next.push(referenceLink(raw));
          continue;
        }
      }
      if (child.type === "text" && child.value) {
        next.push(...split(child.value));
      } else if (child.type === "inlineCode" && isOne(child.value ?? "")) {
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
  };

  // Made once per page kind, so Streamdown keeps one processor for every answer.
  return [() => (tree: MdNode) => transform(tree)];
}

/**
 * The `a` component for answers whose references the plugin marked: a
 * reference goes to `Reference` with the text as written; any other link is
 * the chat's own.
 */
export function referenceComponents(
  Reference: ComponentType<{ raw: string; children?: ReactNode }>
): Components {
  function ReferenceLink(props: ComponentProps<"a"> & { node?: unknown }) {
    const href = typeof props.href === "string" ? props.href : "";
    if (href.startsWith(PREFIX)) {
      return (
        <Reference raw={decodeURIComponent(href.slice(PREFIX.length))}>{props.children}</Reference>
      );
    }
    return <AnswerLink {...props} />;
  }
  return { a: ReferenceLink };
}
