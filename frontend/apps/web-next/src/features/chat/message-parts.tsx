"use client";

import { Download, ExternalLink } from "lucide-react";
import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState, type ReactNode } from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from "@/components/ui/dialog";
import { MessageResponse } from "@/components/ai-elements/message";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { toastApiError } from "@/lib/api/toast";
import type { EneoUIMessage, SessionData, ToolApprovalData } from "@/lib/chat/types";
import { AttachmentPreviewDialog, FileKindIcon, useSignedUrl } from "./attachments";

type Part = EneoUIMessage["parts"][number];
type McpToolReference = Schema<"McpToolReferencePublic">;

/** How many source/web chips to show before collapsing behind a show-more toggle. */
const CHIPS_COLLAPSE_AT = 5;

const chipClass =
  "bg-card hover:border-ring hover:bg-accent flex max-w-full items-center gap-1.5 rounded-lg border py-1.5 pr-2.5 pl-2 text-xs transition-colors";

const moreButtonClass =
  "text-muted-foreground hover:text-foreground hover:border-ring rounded-lg border px-2.5 py-1.5 text-xs transition-colors";

type McpSnippetSource = {
  uri: string;
  content?: string | null;
  pageRange?: string | null;
  section?: string | null;
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

function asString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function hostFromUri(uri: string): string {
  try {
    return new URL(uri).hostname || uri;
  } catch {
    return uri;
  }
}

function mcpMeta(ref: McpToolReference): McpMeta {
  return (ref.meta ?? {}) as McpMeta;
}

function mcpReferenceTitle(ref: McpToolReference): string {
  return asString(mcpMeta(ref).title) ?? hostFromUri(ref.uri);
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

function isHttpUrl(uri: string): boolean {
  return /^https?:\/\//i.test(uri);
}

function safeImageSrc(src: string): string | undefined {
  const normalized = src
    .split("")
    .filter((char) => char.charCodeAt(0) > 0x20)
    .join("")
    .toLowerCase();
  const match = /^([a-z][a-z0-9+.-]*):/.exec(normalized);
  if (!match) return src;
  if (match[1] === "data") return /^data:image\//.test(normalized) ? src : undefined;
  return match[1] === "http" || match[1] === "https" ? src : undefined;
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
      return {
        key: `doc-${source.sourceId}`,
        title: source.title || source.sourceId,
        url: eneo.metadata?.url ?? undefined,
        sourceId: source.sourceId
      };
    });
  const web: SourceChip[] = [...webReferencesFromParts(parts), ...(webReferences ?? [])].map(
    (ref) => ({
      key: `web-${ref.id}`,
      title: ref.title || ref.url,
      url: ref.url,
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
      const externalUrl = sourceType === "crawl-page" && isHttpUrl(ref.uri) ? ref.uri : undefined;
      return {
        key: `mcp-${ref.id}`,
        title: mcpSourceLabel(ref),
        url: externalUrl,
        sourceId: ref.id,
        mcpSnippet: externalUrl
          ? undefined
          : {
              uri: ref.uri,
              content: ref.content,
              pageRange,
              section
            }
      };
    });
  return [...docs, ...web, ...mcp];
}

/**
 * Unified provenance: one numbered "sources" section (documents + web) with
 * show-more. Each chip carries a `{idPrefix}-cite-N` anchor so inline citations
 * can jump to it.
 */
function McpResourceSnippetDialog({
  source,
  snippet,
  children
}: {
  source: SourceChip;
  snippet: McpSnippetSource;
  children: ReactNode;
}) {
  const t = useTranslations();
  const isHttp = isHttpUrl(snippet.uri);

  return (
    <Dialog>
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent className="max-h-[85vh] sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{source.title}</DialogTitle>
          <DialogDescription>
            {t("mcp_resource_snippet_description", { title: source.title })}
          </DialogDescription>
        </DialogHeader>
        <div className="min-h-0 overflow-y-auto rounded-lg border p-4">
          {(snippet.section || snippet.pageRange) && (
            <p className="text-muted-foreground mb-3 text-sm">
              {snippet.section}
              {snippet.section && snippet.pageRange ? " · " : null}
              {snippet.pageRange
                ? t("mcp_resource_page_range", { pageRange: snippet.pageRange })
                : null}
            </p>
          )}
          {snippet.content ? (
            <MessageResponse className="font-voice text-[15px] leading-[1.7]">
              {snippet.content}
            </MessageResponse>
          ) : (
            <p className="text-muted-foreground text-sm italic">
              {t("mcp_resource_unknown_source")}
            </p>
          )}
        </div>
        <DialogFooter className="sm:justify-between">
          {isHttp ? (
            <Button variant="outline" asChild>
              <a href={snippet.uri} target="_blank" rel="noreferrer">
                <ExternalLink aria-hidden="true" className="size-4" />
                {t("mcp_resource_open_external")}
              </a>
            </Button>
          ) : (
            <span />
          )}
          <DialogClose asChild>
            <Button>{t("done")}</Button>
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function MessageSources({ sources, idPrefix }: { sources: SourceChip[]; idPrefix: string }) {
  const t = useTranslations();
  const [expanded, setExpanded] = useState(false);
  if (sources.length === 0) return null;

  const visible = expanded ? sources : sources.slice(0, CHIPS_COLLAPSE_AT);
  const hidden = sources.length - visible.length;

  return (
    <div className="mt-3 flex flex-col gap-2">
      <span className="text-muted-foreground text-xs">
        {t("chat_sources_label")} · {sources.length}
      </span>
      <div className="flex flex-wrap gap-2">
        {visible.map((source, index) => {
          const body = (
            <>
              <span className="bg-secondary text-secondary-foreground flex size-4 shrink-0 items-center justify-center rounded-[4px] text-[10px] font-bold">
                {index + 1}
              </span>
              <span className="truncate">{source.title}</span>
            </>
          );
          const anchorId = `${idPrefix}-cite-${index + 1}`;
          if (source.mcpSnippet) {
            return (
              <McpResourceSnippetDialog
                key={source.key}
                source={source}
                snippet={source.mcpSnippet}
              >
                <button
                  id={anchorId}
                  type="button"
                  title={source.title}
                  className={`${chipClass} scroll-mt-24 text-left`}
                >
                  {body}
                </button>
              </McpResourceSnippetDialog>
            );
          }
          return source.url ? (
            <a
              key={source.key}
              id={anchorId}
              href={source.url}
              target="_blank"
              rel="noreferrer"
              title={source.title}
              className={`${chipClass} scroll-mt-24`}
            >
              {body}
            </a>
          ) : (
            <span
              key={source.key}
              id={anchorId}
              title={source.title}
              className={`${chipClass} scroll-mt-24`}
            >
              {body}
            </span>
          );
        })}
        {sources.length > CHIPS_COLLAPSE_AT && (
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            className={moreButtonClass}
          >
            {expanded ? t("chat_sources_less") : t("chat_sources_more", { count: hidden })}
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * MCP tool approval card for the data-tool-approval part. Each tool can be
 * approved/denied individually (the backend accepts a partial array of
 * decisions and tracks the remainder); a batch all-approve/all-deny is offered
 * when more than one tool is still pending. The still-open stream continues
 * server-side as decisions arrive.
 */
export function ToolApprovalCard({
  data,
  onResolved
}: {
  data: ToolApprovalData;
  onResolved?: () => void;
}) {
  const t = useTranslations();
  const [decisions, setDecisions] = useState<Record<string, "approved" | "denied">>({});

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
    onError: (error) => toastApiError(error, t)
  });

  const timedOut = data.status === "timeout_denied";
  const pending = data.tools.filter((tool) => tool.tool_call_id && !decisions[tool.tool_call_id]);
  const decideAll = (approved: boolean) =>
    submit.mutate(pending.map((tool) => ({ tool_call_id: tool.tool_call_id ?? "", approved })));

  return (
    <Alert>
      <AlertTitle>{t("chat_tool_awaiting_approval")}</AlertTitle>
      <AlertDescription>
        <div className="flex flex-col gap-2">
          <ul className="flex flex-col gap-2">
            {data.tools.map((tool, index) => {
              const decision = tool.tool_call_id ? decisions[tool.tool_call_id] : undefined;
              return (
                <li
                  key={tool.tool_call_id ?? index}
                  className="flex items-center justify-between gap-2"
                >
                  <span className="font-mono text-xs">
                    {tool.server_name}/{tool.tool_name}
                  </span>
                  {timedOut ? (
                    <Badge variant="outline">{t("tool_rejected_by_user")}</Badge>
                  ) : decision ? (
                    <Badge variant={decision === "approved" ? "default" : "destructive"}>
                      {decision === "approved" ? t("tool_accept") : t("tool_deny")}
                    </Badge>
                  ) : (
                    <div className="flex gap-1">
                      <Button
                        size="sm"
                        disabled={submit.isPending}
                        onClick={() =>
                          submit.mutate([{ tool_call_id: tool.tool_call_id ?? "", approved: true }])
                        }
                      >
                        {t("tool_accept")}
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={submit.isPending}
                        onClick={() =>
                          submit.mutate([
                            { tool_call_id: tool.tool_call_id ?? "", approved: false }
                          ])
                        }
                      >
                        {t("tool_deny")}
                      </Button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
          {!timedOut && pending.length > 1 && (
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={submit.isPending}
                onClick={() => decideAll(true)}
              >
                {t("tool_accept_all", { count: pending.length })}
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={submit.isPending}
                onClick={() => decideAll(false)}
              >
                {t("tool_deny_all")}
              </Button>
            </div>
          )}
        </div>
      </AlertDescription>
    </Alert>
  );
}

/** An image attached to or generated by a message, loaded inline. */
export function InlineImage({ file }: { file: Schema<"FilePublic"> }) {
  const url = useSignedUrl(file.id);

  if (!url) {
    return <div className="bg-muted h-40 w-56 max-w-full animate-pulse rounded-lg border" />;
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element -- signed cross-origin URL
    <img src={url} alt={file.name} className="max-h-96 rounded-lg border" />
  );
}

/** A non-image attachment shown as a compact card. */
function FileCard({ file }: { file: Schema<"FilePublic"> }) {
  return (
    <div className="bg-card group-hover:bg-accent flex max-w-full items-center gap-2 rounded-lg border px-3 py-2 text-xs transition-colors">
      <FileKindIcon mimetype={file.mimetype} className="text-muted-foreground size-4 shrink-0" />
      <span className="truncate">{file.name}</span>
    </div>
  );
}

function providerFile(part: Extract<Part, { type: "file" }>): Partial<Schema<"FilePublic">> {
  return ((part.providerMetadata?.eneo ?? {}) as Partial<Schema<"FilePublic">>) ?? {};
}

function fileNameFromPart(part: Extract<Part, { type: "file" }>): string {
  return part.filename ?? providerFile(part).name ?? part.mediaType;
}

function DownloadFileCard({
  name,
  mimetype,
  url
}: {
  name: string;
  mimetype: string;
  url: string;
}) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      download={name}
      className="bg-card hover:bg-accent focus-visible:ring-ring flex max-w-full items-center gap-2 rounded-lg border px-3 py-2 text-xs transition-colors focus-visible:ring-2 focus-visible:outline-none"
    >
      <FileKindIcon mimetype={mimetype} className="text-muted-foreground size-4 shrink-0" />
      <span className="truncate">{name}</span>
      <Download aria-hidden="true" className="text-muted-foreground ml-auto size-3.5 shrink-0" />
    </a>
  );
}

export function MessageFilePart({ part }: { part: Extract<Part, { type: "file" }> }) {
  const name = fileNameFromPart(part);

  if (part.mediaType.startsWith("image/")) {
    return (
      // eslint-disable-next-line @next/next/no-img-element -- signed cross-origin URL or local data URL
      <img src={part.url} alt={name} className="max-h-96 rounded-lg border" />
    );
  }

  return <DownloadFileCard name={name} mimetype={part.mediaType} url={part.url} />;
}

/** Opens a message attachment in the shared preview dialog (signs the URL on open). */
function MessageFilePreview({
  file,
  onClose
}: {
  file: Schema<"FilePublic">;
  onClose: () => void;
}) {
  const url = useSignedUrl(file.id);
  return (
    <AttachmentPreviewDialog
      open
      onOpenChange={(next) => !next && onClose()}
      name={file.name}
      mimetype={file.mimetype}
      url={url}
    />
  );
}

/** Files attached to a message: images inline, documents as cards; click to preview. */
export function MessageFiles({ files }: { files: Schema<"FilePublic">[] }) {
  const [preview, setPreview] = useState<Schema<"FilePublic"> | null>(null);
  if (files.length === 0) return null;
  const images = files.filter((file) => file.mimetype.startsWith("image/"));
  const docs = files.filter((file) => !file.mimetype.startsWith("image/"));

  return (
    <div className="flex flex-col gap-2">
      {images.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {images.map((file) => (
            <button
              key={file.id}
              type="button"
              aria-label={file.name}
              onClick={() => setPreview(file)}
              className="focus-visible:ring-ring rounded-lg focus-visible:ring-2 focus-visible:outline-none"
            >
              <InlineImage file={file} />
            </button>
          ))}
        </div>
      )}
      {docs.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {docs.map((file) => (
            <button
              key={file.id}
              type="button"
              onClick={() => setPreview(file)}
              className="group text-left"
            >
              <FileCard file={file} />
            </button>
          ))}
        </div>
      )}
      {preview && <MessageFilePreview file={preview} onClose={() => setPreview(null)} />}
    </div>
  );
}

/** Display-only image references returned from MCP resource_link blocks. */
export function McpImageStrip({ references }: { references: McpToolReference[] }) {
  const images = references
    .filter(isMcpImageReference)
    .map((reference) => ({
      reference,
      src: safeImageSrc(reference.uri),
      title: mcpReferenceTitle(reference)
    }))
    .filter((image): image is { reference: McpToolReference; src: string; title: string } =>
      Boolean(image.src)
    );

  if (images.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2 pt-2">
      {images.map(({ reference, src, title }) => (
        <div key={reference.id} className="max-w-80 overflow-hidden rounded-lg border shadow-sm">
          {/* eslint-disable-next-line @next/next/no-img-element -- external MCP resource URL */}
          <img src={src} alt={title} className="max-h-96 w-auto object-contain" />
        </div>
      ))}
    </div>
  );
}

/** Renders a generated image file from an assistant message. */
export function GeneratedFile({ file }: { file: Schema<"FilePublic"> }) {
  const url = useSignedUrl(file.id);

  if (file.mimetype.startsWith("image/")) return <InlineImage file={file} />;
  if (!url) return <FileCard file={file} />;
  return <DownloadFileCard name={file.name} mimetype={file.mimetype} url={url} />;
}
