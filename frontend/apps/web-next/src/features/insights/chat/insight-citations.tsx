import { useTranslations } from "use-intl";
import { createContext, use, type ComponentProps } from "react";
import type { MessageResponseProps } from "@/components/ai-elements/message";
import { AnswerLink } from "@/features/chat/answer-links";
import type { ChatReferences } from "@/features/chat/chat-references";

/**
 * Conversations an analysis cites. The analysis is told to cite every
 * example as `(session <uuid>)`, with the ids its tools return (which write
 * them `session_id=<uuid>`). A remark plugin turns each such citation in an
 * answer into a `#insight-session-<uuid>` link node, and the `a` component
 * draws exactly those as buttons that open the conversation. Code keeps its
 * text, except a citation the answer put in backticks on its own. Every
 * other link goes on to the chat's own link.
 */

type MdNode = { type: string; value?: string; url?: string; children?: MdNode[] };

const UUID = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";
const CITATION = new RegExp(`\\bsession(?:_id)?[\\s=:]*(${UUID})`, "gi");
const ONE_CITATION = new RegExp(`^\\s*session(?:_id)?[\\s=:]*(${UUID})\\s*$`, "i");
const PREFIX = "#insight-session-";
const LINK = new RegExp(`^${PREFIX}(${UUID})$`);

/** The start of a conversation's id, as an answer names it to a person. */
export function shortSessionId(sessionId: string): string {
  return sessionId.slice(0, 8);
}

function citationLink(sessionId: string): MdNode {
  return {
    type: "link",
    url: PREFIX + sessionId.toLowerCase(),
    children: [{ type: "text", value: shortSessionId(sessionId) }]
  };
}

function splitCitations(value: string): MdNode[] {
  const out: MdNode[] = [];
  let cursor = 0;
  for (const match of value.matchAll(CITATION)) {
    const start = match.index ?? 0;
    if (start > cursor) out.push({ type: "text", value: value.slice(cursor, start) });
    out.push(citationLink(match[1]!));
    cursor = start + match[0].length;
  }
  if (out.length === 0) return [{ type: "text", value }];
  if (cursor < value.length) out.push({ type: "text", value: value.slice(cursor) });
  return out;
}

function transform(node: MdNode) {
  if (!node.children) return;
  const next: MdNode[] = [];
  for (const child of node.children) {
    const cited = child.type === "inlineCode" ? ONE_CITATION.exec(child.value ?? "") : null;
    if (child.type === "text" && child.value) {
      next.push(...splitCitations(child.value));
    } else if (cited) {
      next.push(citationLink(cited[1]!));
    } else {
      if (child.type !== "code" && child.type !== "inlineCode" && child.type !== "link") {
        transform(child);
      }
      next.push(child);
    }
  }
  node.children = next;
}

function citationsRemark() {
  return (tree: MdNode) => transform(tree);
}

/** Stable, so Streamdown keeps one processor for every answer. */
const citationRemarkPlugins: NonNullable<MessageResponseProps["remarkPlugins"]> = [citationsRemark];

/** Opens a cited conversation; `trigger` is the citation, for focus to return to. */
export type OpenCitedConversation = (sessionId: string, trigger: HTMLElement) => void;

export const InsightCitationsContext = createContext<OpenCitedConversation | null>(null);

const CITATION_CLASS =
  "text-ax-text-accent focus-visible:outline-ring rounded-ax-inner font-[inherit] underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-offset-2";

function CitationLink(props: ComponentProps<"a"> & { node?: unknown }) {
  const t = useTranslations();
  const open = use(InsightCitationsContext);
  const match = typeof props.href === "string" ? LINK.exec(props.href) : null;
  if (!match) return <AnswerLink {...props} />;
  const sessionId = match[1]!;
  const label = t("insights_chat_cited_conversation", { id: shortSessionId(sessionId) });
  if (!open) return <>{label}</>;
  return (
    // Named by its words alone, as the answer reads (WCAG 2.5.3); it opens a dialog.
    <button
      type="button"
      aria-haspopup="dialog"
      onClick={(event) => open(sessionId, event.currentTarget)}
      className={CITATION_CLASS}
    >
      {label}
    </button>
  );
}

const citationComponents: NonNullable<MessageResponseProps["components"]> = { a: CitationLink };

/** The insights chat's references: cited conversations in its answers, nothing in the composer. */
export const insightCitationReferences: ChatReferences = {
  remarkPlugins: citationRemarkPlugins,
  components: citationComponents
};
