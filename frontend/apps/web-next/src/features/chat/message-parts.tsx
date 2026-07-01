"use client";

import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { toastApiError } from "@/lib/api/toast";
import type { EneoUIMessage, ToolApprovalData } from "@/lib/chat/types";
import { AttachmentPreviewDialog, FileKindIcon, useSignedUrl } from "./attachments";

type Part = EneoUIMessage["parts"][number];

/** How many source/web chips to show before collapsing behind a show-more toggle. */
const CHIPS_COLLAPSE_AT = 5;

const chipClass =
  "bg-card hover:border-ring hover:bg-accent flex max-w-full items-center gap-1.5 rounded-lg border py-1.5 pr-2.5 pl-2 text-xs transition-colors";

const moreButtonClass =
  "text-muted-foreground hover:text-foreground hover:border-ring rounded-lg border px-2.5 py-1.5 text-xs transition-colors";

type SourceChip = { key: string; title: string; url?: string };

/**
 * Unified provenance: knowledge documents and web references shown as one
 * numbered "sources" section, collapsed to the first few behind a show-more
 * toggle. One section instead of two stacked rows.
 */
export function MessageSources({
  parts,
  webReferences
}: {
  parts: Part[];
  webReferences?: { id: string; title: string; url: string }[];
}) {
  const t = useTranslations();
  const [expanded, setExpanded] = useState(false);

  const docs: SourceChip[] = parts
    .filter((part) => part.type === "source-document")
    .map((source) => {
      const eneo = (source.providerMetadata?.eneo ?? {}) as { metadata?: { url?: string | null } };
      return {
        key: `doc-${source.sourceId}`,
        title: source.title || source.sourceId,
        url: eneo.metadata?.url ?? undefined
      };
    });
  const web: SourceChip[] = (webReferences ?? []).map((ref) => ({
    key: `web-${ref.id}`,
    title: ref.title || ref.url,
    url: ref.url
  }));
  const sources = [...docs, ...web];
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
          return source.url ? (
            <a
              key={source.key}
              href={source.url}
              target="_blank"
              rel="noreferrer"
              className={chipClass}
            >
              {body}
            </a>
          ) : (
            <span key={source.key} className={chipClass}>
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

/** Renders a generated image file from an assistant message. */
export function GeneratedFile({ file }: { file: Schema<"FilePublic"> }) {
  if (!file.mimetype.startsWith("image/")) return null;
  return <InlineImage file={file} />;
}
