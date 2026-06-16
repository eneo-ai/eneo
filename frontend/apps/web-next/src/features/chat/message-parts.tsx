"use client";

import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import {
  Tool,
  ToolContent,
  ToolHeader,
  ToolInput,
  ToolOutput
} from "@/components/ai-elements/tool";
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

/** Numbered source chips, per the design's chat thread. */
export function MessageSources({ parts }: { parts: Part[] }) {
  const sources = parts.filter((part) => part.type === "source-document");
  if (sources.length === 0) return null;

  const chipClass =
    "bg-card hover:border-ring hover:bg-accent flex max-w-full items-center gap-1.5 rounded-lg border py-1.5 pr-2.5 pl-2 text-xs transition-colors";

  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {sources.map((source, index) => {
        const eneo = (source.providerMetadata?.eneo ?? {}) as {
          metadata?: { url?: string | null };
        };
        const url = eneo.metadata?.url ?? undefined;
        const body = (
          <>
            <span className="bg-secondary text-secondary-foreground flex size-4 shrink-0 items-center justify-center rounded-[4px] text-[10px] font-bold">
              {index + 1}
            </span>
            <span className="truncate">{source.title || source.sourceId}</span>
          </>
        );
        return url ? (
          <a
            key={source.sourceId}
            href={url}
            target="_blank"
            rel="noreferrer"
            className={chipClass}
          >
            {body}
          </a>
        ) : (
          <span key={source.sourceId} className={chipClass}>
            {body}
          </span>
        );
      })}
    </div>
  );
}

export function MessageTool({ part }: { part: Extract<Part, { type: "dynamic-tool" }> }) {
  return (
    <Tool>
      <ToolHeader title={part.toolName} type={`tool-${part.toolName}`} state={part.state} />
      <ToolContent>
        <ToolInput input={part.input} />
        <ToolOutput
          errorText={part.state === "output-error" ? part.errorText : undefined}
          output={
            part.state === "output-available" ? JSON.stringify(part.output, null, 2) : undefined
          }
        />
      </ToolContent>
    </Tool>
  );
}

/**
 * MCP tool approval card for the data-tool-approval part. Approving/denying
 * posts the decisions; the still-open stream then continues server-side.
 */
export function ToolApprovalCard({
  data,
  onResolved
}: {
  data: ToolApprovalData;
  onResolved?: () => void;
}) {
  const t = useTranslations();
  const [resolved, setResolved] = useState<"approved" | "denied" | null>(null);

  const submit = useMutation({
    mutationFn: (approved: boolean) =>
      unwrap(
        browserApi.POST("/api/v1/conversations/approve-tools/", {
          params: { query: { approval_id: data.approval_id } },
          body: data.tools.map((tool) => ({
            tool_call_id: tool.tool_call_id ?? "",
            approved
          }))
        })
      ),
    onSuccess: (_, approved) => {
      setResolved(approved ? "approved" : "denied");
      onResolved?.();
    },
    onError: (error) => toastApiError(error, t)
  });

  const timedOut = data.status === "timeout_denied";

  return (
    <Alert>
      <AlertTitle>{t("chat_tool_awaiting_approval")}</AlertTitle>
      <AlertDescription>
        <div className="flex flex-col gap-2">
          <ul className="flex flex-col gap-1">
            {data.tools.map((tool, index) => (
              <li key={tool.tool_call_id ?? index} className="font-mono text-xs">
                {tool.server_name}/{tool.tool_name}
              </li>
            ))}
          </ul>
          {timedOut ? (
            <Badge variant="outline">{t("tool_rejected_by_user")}</Badge>
          ) : resolved ? (
            <Badge variant={resolved === "approved" ? "default" : "destructive"}>
              {resolved === "approved" ? t("approve") : t("tool_deny")}
            </Badge>
          ) : (
            <div className="flex gap-2">
              <Button size="sm" disabled={submit.isPending} onClick={() => submit.mutate(true)}>
                {t("approve")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={submit.isPending}
                onClick={() => submit.mutate(false)}
              >
                {t("tool_deny")}
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
