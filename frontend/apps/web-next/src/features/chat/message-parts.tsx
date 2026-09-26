"use client";

import { Button as AxButton } from "@astryxdesign/core/Button";
import { useMutation } from "@tanstack/react-query";
import { Download, ExternalLink, ShieldAlert, ShieldCheck, ShieldX } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useId, useState, type ReactNode } from "react";
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
import { cn } from "@/lib/utils";
import { AttachmentPreviewDialog, FileTypeTile, useSignedUrl } from "./attachments";
import { formatFileSize } from "./format";

type Part = EneoUIMessage["parts"][number];
type McpToolReference = Schema<"McpToolReferencePublic">;

export type McpSnippetSource = {
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

/** Shows an MCP resource's snippet (content, section, page range) in a dialog. */
export function McpResourceSnippetDialog({
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
  const pending = timedOut
    ? []
    : data.tools.filter((tool) => tool.tool_call_id && !decisions[tool.tool_call_id]);
  const decideAll = (approved: boolean) =>
    submit.mutate(pending.map((tool) => ({ tool_call_id: tool.tool_call_id ?? "", approved })));

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
          const decision = tool.tool_call_id ? decisions[tool.tool_call_id] : undefined;
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
                    isDisabled={submit.isPending}
                    onClick={() =>
                      submit.mutate([{ tool_call_id: tool.tool_call_id ?? "", approved: true }])
                    }
                  >
                    {t("tool_accept")}
                  </AxButton>
                  <AxButton
                    label={t("chat_tool_deny_named", { tool: name })}
                    variant="secondary"
                    size="sm"
                    isDisabled={submit.isPending}
                    onClick={() =>
                      submit.mutate([{ tool_call_id: tool.tool_call_id ?? "", approved: false }])
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
            isDisabled={submit.isPending}
            onClick={() => decideAll(true)}
          />
          <AxButton
            label={t("tool_deny_all")}
            variant="secondary"
            size="sm"
            isDisabled={submit.isPending}
            onClick={() => decideAll(false)}
          />
        </div>
      )}
    </section>
  );
}

/** An image attached to or generated by a message, loaded inline. */
export function InlineImage({ file }: { file: Schema<"FilePublic"> }) {
  const url = useSignedUrl(file.id);

  if (!url) {
    return <div className="bg-ax-muted rounded-ax-container h-40 w-56 max-w-full animate-pulse" />;
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element -- signed cross-origin URL
    <img
      src={url}
      alt={file.name}
      className="border-ax-border rounded-ax-container max-h-96 border"
    />
  );
}

/** A file as a compact token: coloured type tile, name, size. */
function FileTokenBody({
  name,
  mimetype,
  size
}: {
  name: string;
  mimetype: string;
  size?: number | null;
}) {
  const locale = useLocale();
  return (
    <>
      <FileTypeTile mimetype={mimetype} size="sm" />
      <span className="min-w-0 truncate font-semibold">{name}</span>
      {size ? (
        <span className="text-ax-text-secondary shrink-0">{formatFileSize(size, locale)}</span>
      ) : null}
    </>
  );
}

const FILE_TOKEN_CLASS =
  "border-ax-border focus-visible:outline-ring flex h-8 max-w-full items-center gap-2 rounded-ax-element border py-0 ps-1 pe-2.5 text-[12.5px] transition-colors hover:bg-ax-hover focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:h-11";

function providerFile(part: Extract<Part, { type: "file" }>): Partial<Schema<"FilePublic">> {
  return ((part.providerMetadata?.eneo ?? {}) as Partial<Schema<"FilePublic">>) ?? {};
}

function fileNameFromPart(part: Extract<Part, { type: "file" }>): string {
  return part.filename ?? providerFile(part).name ?? part.mediaType;
}

function DownloadFileToken({
  name,
  mimetype,
  size,
  url
}: {
  name: string;
  mimetype: string;
  size?: number | null;
  url: string;
}) {
  const t = useTranslations();
  return (
    <a href={url} target="_blank" rel="noreferrer" download={name} className={FILE_TOKEN_CLASS}>
      <FileTokenBody name={name} mimetype={mimetype} size={size} />
      <Download aria-hidden="true" className="text-ax-text-secondary size-3.5 shrink-0" />
      <span className="sr-only">{t("download")}</span>
    </a>
  );
}

export function MessageFilePart({ part }: { part: Extract<Part, { type: "file" }> }) {
  const name = fileNameFromPart(part);

  if (part.mediaType.startsWith("image/")) {
    return (
      // eslint-disable-next-line @next/next/no-img-element -- signed cross-origin URL or local data URL
      <img
        src={part.url}
        alt={name}
        className="border-ax-border rounded-ax-container max-h-96 border"
      />
    );
  }

  return (
    <DownloadFileToken
      name={name}
      mimetype={part.mediaType}
      size={providerFile(part).size}
      url={part.url}
    />
  );
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

/**
 * Files attached to a user message: images as thumbnails, documents as file
 * tokens (type tile, name, size). Each opens the preview.
 */
export function MessageFiles({ files }: { files: Schema<"FilePublic">[] }) {
  const t = useTranslations();
  const [preview, setPreview] = useState<Schema<"FilePublic"> | null>(null);
  if (files.length === 0) return null;
  const images = files.filter((file) => file.mimetype.startsWith("image/"));
  const docs = files.filter((file) => !file.mimetype.startsWith("image/"));

  return (
    <div className="flex max-w-full flex-col items-end gap-1.5">
      {images.length > 0 && (
        <ul className="flex flex-wrap justify-end gap-1.5" aria-label={t("attachments")}>
          {images.map((file) => (
            <li key={file.id}>
              <button
                type="button"
                aria-label={t("chat_preview_file", { name: file.name })}
                onClick={() => setPreview(file)}
                className="focus-visible:outline-ring rounded-ax-container block focus-visible:outline-2 focus-visible:outline-offset-2"
              >
                <InlineImage file={file} />
              </button>
            </li>
          ))}
        </ul>
      )}
      {docs.length > 0 && (
        <ul className="flex flex-wrap justify-end gap-1.5" aria-label={t("attachments")}>
          {docs.map((file) => (
            <li key={file.id} className="max-w-full">
              <button type="button" onClick={() => setPreview(file)} className={FILE_TOKEN_CLASS}>
                <span className="sr-only">{t("preview")}: </span>
                <FileTokenBody name={file.name} mimetype={file.mimetype} size={file.size} />
              </button>
            </li>
          ))}
        </ul>
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

/** Renders a generated file from an assistant message (images inline, others as download tokens). */
export function GeneratedFile({ file }: { file: Schema<"FilePublic"> }) {
  const url = useSignedUrl(file.id);

  if (file.mimetype.startsWith("image/")) return <InlineImage file={file} />;
  if (!url) {
    return (
      <span className={FILE_TOKEN_CLASS}>
        <FileTokenBody name={file.name} mimetype={file.mimetype} size={file.size} />
      </span>
    );
  }
  return <DownloadFileToken name={file.name} mimetype={file.mimetype} size={file.size} url={url} />;
}
