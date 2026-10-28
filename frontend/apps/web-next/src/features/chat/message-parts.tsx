"use client";

import { Button as AxButton } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { HStack, Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { Skeleton } from "@astryxdesign/core/Skeleton";
import { useMutation } from "@tanstack/react-query";
import { ExternalLink, ShieldAlert, ShieldCheck, ShieldX } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";
import { ANSWER_TEXT_CLASS, MessageResponse } from "@/components/ai-elements/message";
import { useReturnFocus } from "@/components/ui/dialog-focus";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { toastApiError } from "@/lib/api/toast";
import { asString, hostOf } from "@/lib/chat/metadata";
import type { EneoUIMessage, SessionData, ToolApprovalData, ToolCallInfo } from "@/lib/chat/types";
import { sanitizeImageSrc, sanitizeWebHref } from "@/lib/safe-url";
import { cn } from "@/lib/utils";
import { FileTypeTile, useSignedUrl } from "./attachments";
import { fileExtension, formatBytes } from "@/lib/format";

type Part = EneoUIMessage["parts"][number];
type McpToolReference = Schema<"McpToolReferencePublic">;

export type McpSnippetSource = {
  uri: string;
  content?: string | null;
  pageRange?: string | null;
  section?: string | null;
  excerptNumber?: number;
};

export type SourceChip = {
  key: string;
  title: string;
  url?: string;
  sourceId: string;
  mcpSnippet?: McpSnippetSource;
};

type McpMeta = {
  sourceType?: unknown;
  title?: unknown;
  pageRange?: unknown;
  section?: unknown;
};

function mcpMeta(ref: McpToolReference): McpMeta {
  return (ref.meta ?? {}) as McpMeta;
}

function mcpReferenceTitle(ref: McpToolReference): string {
  return asString(mcpMeta(ref).title) ?? hostOf(ref.uri) ?? ref.uri;
}

function mcpSourceLabel(ref: McpToolReference): string {
  const meta = mcpMeta(ref);
  const title = mcpReferenceTitle(ref);
  const section = asString(meta.section);
  return section ? `${title} -> ${section}` : title;
}

function isMcpImageReference(ref: McpToolReference): boolean {
  return (ref.mime_type ?? "").startsWith("image/");
}

/** Knowledge references identify excerpts by zero-based chunk number in their URI. */
function knowledgeExcerptNumber(uri: string): number | undefined {
  const match = /^eneo:\/\/info-blob\/[^#]+#chunk-(\d+)$/.exec(uri);
  if (!match) return undefined;
  const number = Number(match[1]);
  return Number.isSafeInteger(number) ? number + 1 : undefined;
}

/** The MCP resource's title and internal document ID are tool context, not excerpt text. */
function mcpSnippetContent(
  uri: string,
  content: string | null | undefined
): string | null | undefined {
  if (!content || !uri.startsWith("eneo://info-blob/")) return content;
  return content.replace(/^Title:[^\r\n]*\r?\ndocument_id:[^\r\n]*\r?\n\r?\n/, "");
}

export function sessionDataFromParts(parts: Part[]): SessionData | null {
  const session = parts.find((part) => part.type === "data-session");
  return session?.type === "data-session" ? session.data : null;
}

export function answeringAssistantFromParts(parts: Part[]): SessionData["answering_assistant"] {
  return sessionDataFromParts(parts)?.answering_assistant ?? null;
}

function webReferencesFromParts(parts: Part[]): SessionData["web_search_references"] {
  return sessionDataFromParts(parts)?.web_search_references ?? [];
}

function addMcpReferences(
  seen: Set<string>,
  target: McpToolReference[],
  references?: McpToolReference[] | null
) {
  for (const reference of references ?? []) {
    if (!reference?.id || seen.has(reference.id)) continue;
    seen.add(reference.id);
    target.push(reference);
  }
}

export function mcpReferencesFromParts(
  parts: Part[],
  metadataReferences?: McpToolReference[]
): McpToolReference[] {
  const seen = new Set<string>();
  const references: McpToolReference[] = [];
  addMcpReferences(seen, references, sessionDataFromParts(parts)?.mcp_tool_references);
  for (const part of parts) {
    if (part.type === "data-mcp-tool-references") {
      addMcpReferences(seen, references, part.data.mcp_tool_references);
    }
  }
  addMcpReferences(seen, references, metadataReferences);
  return references;
}

/** Merge a message's knowledge documents and web references into one ordered list. */
export function mergeSources(
  parts: Part[],
  webReferences?: { id: string; title: string; url: string }[],
  mcpReferences: McpToolReference[] = []
): SourceChip[] {
  const docs: SourceChip[] = parts
    .filter((part) => part.type === "source-document")
    .map((source) => {
      const eneo = (source.providerMetadata?.eneo ?? {}) as { metadata?: { url?: string | null } };
      const url = eneo.metadata?.url;
      return {
        key: `doc-${source.sourceId}`,
        title: source.title || source.sourceId,
        // A document's stored url is whatever its editor wrote; only http(s) links out.
        url: sanitizeWebHref(url),
        sourceId: source.sourceId
      };
    });
  const web: SourceChip[] = [...webReferencesFromParts(parts), ...(webReferences ?? [])].map(
    (ref) => ({
      key: `web-${ref.id}`,
      title: ref.title || ref.url,
      url: sanitizeWebHref(ref.url),
      sourceId: ref.id
    })
  );
  const mcp: SourceChip[] = mcpReferences
    .filter((ref) => !isMcpImageReference(ref))
    .map((ref) => {
      const meta = mcpMeta(ref);
      const sourceType = asString(meta.sourceType);
      const pageRange = asString(meta.pageRange);
      const section = asString(meta.section);
      const externalUrl = sourceType === "crawl-page" ? sanitizeWebHref(ref.uri) : undefined;
      const excerptNumber = knowledgeExcerptNumber(ref.uri);
      return {
        key: `mcp-${ref.id}`,
        title: mcpSourceLabel(ref),
        url: externalUrl,
        sourceId: ref.id,
        mcpSnippet: externalUrl
          ? undefined
          : {
              uri: ref.uri,
              content: mcpSnippetContent(ref.uri, ref.content),
              pageRange,
              section,
              ...(excerptNumber === undefined ? {} : { excerptNumber })
            }
      };
    });
  return [...docs, ...web, ...mcp];
}

/**
 * A source's title as a button that shows the MCP resource's snippet (content,
 * section, page range) in an Astryx Dialog.
 */
export function McpSnippetButton({
  source,
  snippet,
  className
}: {
  source: SourceChip;
  snippet: McpSnippetSource;
  className?: string;
}) {
  const t = useTranslations();
  const excerptLabel = snippet.excerptNumber
    ? t("chat_source_excerpt", { number: snippet.excerptNumber })
    : null;
  const externalHref = sanitizeWebHref(snippet.uri);
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  // Astryx returns focus to what had it at open; this also covers a tap that
  // never focused the button (Safari).
  useReturnFocus(open, triggerRef);

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="dialog"
        onClick={() => setOpen(true)}
        className={className}
      >
        {source.title}
        {excerptLabel && <span className="sr-only"> {excerptLabel}</span>}
      </button>
      <Dialog isOpen={open} onOpenChange={setOpen} width={672} maxHeight="85dvh">
        <Layout
          header={
            <DialogHeader
              title={excerptLabel ? `${source.title} · ${excerptLabel}` : source.title}
              subtitle={t("mcp_resource_snippet_description", { title: source.title })}
              onOpenChange={setOpen}
            />
          }
          content={
            <LayoutContent>
              {(snippet.section || snippet.pageRange) && (
                <p className="text-ax-text-secondary mb-3 text-sm">
                  {snippet.section}
                  {snippet.section && snippet.pageRange ? " · " : null}
                  {snippet.pageRange
                    ? t("mcp_resource_page_range", { pageRange: snippet.pageRange })
                    : null}
                </p>
              )}
              {snippet.content ? (
                <MessageResponse className={ANSWER_TEXT_CLASS}>{snippet.content}</MessageResponse>
              ) : (
                <p className="text-ax-text-secondary text-sm italic">
                  {t("mcp_resource_unknown_source")}
                </p>
              )}
            </LayoutContent>
          }
          footer={
            <LayoutFooter>
              <HStack gap={2} hAlign="end">
                {externalHref && (
                  <AxButton
                    label={t("mcp_resource_open_external")}
                    variant="secondary"
                    icon={<ExternalLink aria-hidden="true" className="size-4" />}
                    href={externalHref}
                    target="_blank"
                    rel="noreferrer"
                  />
                )}
                <AxButton label={t("done")} variant="primary" onClick={() => setOpen(false)} />
              </HStack>
            </LayoutFooter>
          }
        />
      </Dialog>
    </>
  );
}

/**
 * MCP tool approval card for the data-tool-approval part. Each tool can be
 * approved/denied individually (the backend accepts a partial array of
 * decisions and tracks the remainder); "Godkänn alla" / "Avvisa alla" appear
 * when more than one tool is still pending. The still-open stream continues
 * server-side as decisions arrive. The decisions stay on the card as a record.
 */
export function ToolApprovalCard({
  data,
  onResolved
}: {
  data: ToolApprovalData;
  onResolved?: () => void;
}) {
  const t = useTranslations();
  const headingId = useId();
  const [decisions, setDecisions] = useState<Record<string, "approved" | "denied">>({});
  // The button whose decision is being sent: busy, it stays enabled (Astryx
  // isInterruptible) so it keeps focus, and presses while one is sent are
  // ignored.
  const [running, setRunning] = useState<string | null>(null);

  const submit = useMutation({
    mutationFn: (items: { tool_call_id: string; approved: boolean }[]) =>
      unwrap(
        browserApi.POST("/api/v1/conversations/approve-tools/", {
          params: { query: { approval_id: data.approval_id } },
          body: items
        })
      ),
    onSuccess: (_, items) => {
      setDecisions((prev) => {
        const next = { ...prev };
        for (const item of items) {
          next[item.tool_call_id] = item.approved ? "approved" : "denied";
        }
        return next;
      });
      onResolved?.();
    },
    onError: (error) => toastApiError(error, t),
    onSettled: () => setRunning(null)
  });

  const timedOut = data.status === "timeout_denied";
  // A decision made here wins while its request is in flight; otherwise the
  // stream's decided part (data-tool-approval with status approved/denied,
  // e.g. decided from another tab) names each tool's outcome.
  const decisionFor = (tool: ToolCallInfo): "approved" | "denied" | undefined => {
    const local = tool.tool_call_id ? decisions[tool.tool_call_id] : undefined;
    if (local) return local;
    if (data.status === "pending" || timedOut) return undefined;
    return tool.approved ? "approved" : "denied";
  };
  const pending = timedOut
    ? []
    : data.tools.filter((tool) => tool.tool_call_id && !decisionFor(tool));
  function decide(control: string, items: { tool_call_id: string; approved: boolean }[]) {
    if (running !== null || submit.isPending) return;
    setRunning(control);
    submit.mutate(items);
  }
  const decideAll = (approved: boolean) =>
    decide(
      approved ? "accept-all" : "deny-all",
      pending.map((tool) => ({ tool_call_id: tool.tool_call_id ?? "", approved }))
    );

  return (
    <section
      aria-labelledby={headingId}
      className="border-ax-border bg-ax-card rounded-ax-container flex w-full flex-col gap-3 border p-3.5 font-sans"
    >
      <div className="flex items-start gap-2.5">
        <ShieldAlert aria-hidden="true" className="text-ax-warning mt-0.5 size-4 shrink-0" />
        <div className="flex min-w-0 flex-col gap-0.5">
          <h3 id={headingId} className="text-[13.5px] font-semibold">
            {pending.length > 0 ? t("chat_tool_awaiting_approval") : t("chat_tool_approval_record")}
          </h3>
          {pending.length > 0 && (
            <p className="text-ax-text-secondary text-[13px]">{t("chat_tool_approval_hint")}</p>
          )}
        </div>
      </div>
      <ul className="flex flex-col gap-1.5">
        {data.tools.map((tool, index) => {
          const decision = decisionFor(tool);
          const name = `${tool.server_name}/${tool.tool_name}`;
          return (
            <li
              key={tool.tool_call_id ?? index}
              className="bg-ax-muted rounded-ax-element flex flex-wrap items-center justify-between gap-2 px-2.5 py-2"
            >
              <span className="min-w-0 font-mono text-xs break-all">{name}</span>
              {timedOut ? (
                <span className="text-ax-text-secondary flex items-center gap-1 text-xs font-medium">
                  <ShieldX aria-hidden="true" className="size-3.5" />
                  {t("chat_tool_approval_timed_out")}
                </span>
              ) : decision ? (
                <span
                  className={cn(
                    "flex items-center gap-1 text-xs font-medium",
                    decision === "approved" ? "text-ax-success" : "text-ax-error"
                  )}
                >
                  {decision === "approved" ? (
                    <ShieldCheck aria-hidden="true" className="size-3.5" />
                  ) : (
                    <ShieldX aria-hidden="true" className="size-3.5" />
                  )}
                  {decision === "approved" ? t("chat_tool_approved") : t("chat_tool_denied")}
                </span>
              ) : (
                // Astryx Button names itself from `label` (aria-label) and shows
                // the children: each button names its tool, the text stays short.
                <span className="flex gap-1.5">
                  <AxButton
                    label={t("chat_tool_accept_named", { tool: name })}
                    variant="primary"
                    size="sm"
                    isLoading={running === `accept:${tool.tool_call_id}`}
                    isInterruptible
                    onClick={() =>
                      decide(`accept:${tool.tool_call_id}`, [
                        { tool_call_id: tool.tool_call_id ?? "", approved: true }
                      ])
                    }
                  >
                    {t("tool_accept")}
                  </AxButton>
                  <AxButton
                    label={t("chat_tool_deny_named", { tool: name })}
                    variant="secondary"
                    size="sm"
                    isLoading={running === `deny:${tool.tool_call_id}`}
                    isInterruptible
                    onClick={() =>
                      decide(`deny:${tool.tool_call_id}`, [
                        { tool_call_id: tool.tool_call_id ?? "", approved: false }
                      ])
                    }
                  >
                    {t("tool_deny")}
                  </AxButton>
                </span>
              )}
            </li>
          );
        })}
      </ul>
      {pending.length > 1 && (
        <div className="flex flex-wrap gap-2">
          <AxButton
            label={t("tool_accept_all", { count: pending.length })}
            variant="primary"
            size="sm"
            isLoading={running === "accept-all"}
            isInterruptible
            onClick={() => decideAll(true)}
          />
          <AxButton
            label={t("tool_deny_all")}
            variant="secondary"
            size="sm"
            isLoading={running === "deny-all"}
            isInterruptible
            onClick={() => decideAll(false)}
          />
        </div>
      )}
    </section>
  );
}

/** An image attached to or generated by a message, loaded inline. */
export function InlineImage({ file }: { file: Schema<"FilePublic"> }) {
  const { url, error } = useSignedUrl(file.id);
  const t = useTranslations();

  if (error)
    return (
      <span className="text-muted-foreground text-sm">{t("attachment_error_loading_content")}</span>
    );
  if (!url) {
    return (
      <span className="block h-40 w-56 max-w-full">
        <Skeleton radius={3} />
      </span>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element -- signed file URL
    <img
      src={url}
      alt={file.name}
      className="border-ax-border rounded-ax-container max-h-96 border"
    />
  );
}

/** A file as a compact token: coloured type tile, name, type and size. */
export function FileTokenBody({
  name,
  mimetype,
  size
}: {
  name: string;
  mimetype: string;
  size?: number | null;
}) {
  const locale = useLocale();
  const detail = [fileExtension(name), size ? formatBytes(size, locale) : ""]
    .filter(Boolean)
    .join(" · ");
  return (
    <>
      <FileTypeTile mimetype={mimetype} size="sm" />
      <span className="min-w-0 truncate font-semibold">{name}</span>
      {detail && <span className="text-ax-text-secondary shrink-0 tabular-nums">{detail}</span>}
    </>
  );
}

/** The 32 px chip a file is shown as, beside a message or in the composer. */
export const FILE_CHIP_CLASS =
  "border-ax-border bg-ax-surface flex h-8 max-w-full min-w-0 items-center gap-2 rounded-ax-element border py-0 ps-1 pe-2.5 text-[12.5px] pointer-coarse:h-11";

/** A file chip that does something when pressed: opens, downloads. */
export const FILE_TOKEN_CLASS = `${FILE_CHIP_CLASS} focus-visible:outline-ring transition-colors hover:bg-ax-hover focus-visible:outline-2 focus-visible:outline-offset-2`;

/** Display-only image references returned from MCP resource_link blocks. */
export function McpImageStrip({ references }: { references: McpToolReference[] }) {
  const images = references
    .filter(isMcpImageReference)
    .map((reference) => ({
      reference,
      src: sanitizeImageSrc(reference.uri),
      title: mcpReferenceTitle(reference)
    }))
    .filter((image): image is { reference: McpToolReference; src: string; title: string } =>
      Boolean(image.src)
    );

  if (images.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2 pt-2">
      {images.map(({ reference, src, title }) => (
        <div
          key={reference.id}
          className="border-ax-border rounded-ax-container shadow-ax-low max-w-80 overflow-hidden border"
        >
          {/* eslint-disable-next-line @next/next/no-img-element -- external MCP resource URL */}
          <img src={src} alt={title} className="max-h-96 w-auto object-contain" />
        </div>
      ))}
    </div>
  );
}
