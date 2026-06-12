"use client";

import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Source, Sources, SourcesContent, SourcesTrigger } from "@/components/ai-elements/sources";
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

type Part = EneoUIMessage["parts"][number];

export function MessageSources({ parts }: { parts: Part[] }) {
  const sources = parts.filter((part) => part.type === "source-document");
  if (sources.length === 0) return null;

  return (
    <Sources>
      <SourcesTrigger count={sources.length} />
      <SourcesContent>
        {sources.map((source) => {
          const eneo = (source.providerMetadata?.eneo ?? {}) as {
            metadata?: { url?: string | null };
          };
          return (
            <Source
              key={source.sourceId}
              href={eneo.metadata?.url ?? undefined}
              title={source.title || source.sourceId}
            />
          );
        })}
      </SourcesContent>
    </Sources>
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

/** Renders a generated file (image) from a persisted message on demand. */
export function GeneratedFile({ file }: { file: Schema<"FilePublic"> }) {
  const [url, setUrl] = useState<string | null>(null);

  async function load() {
    const signed = await unwrap(
      browserApi.POST("/api/v1/files/{id}/signed-url/", {
        params: { path: { id: file.id } },
        body: { expires_in: 3600, content_disposition: "inline" }
      })
    );
    setUrl(signed.url);
  }

  if (!file.mimetype.startsWith("image/")) return null;
  if (!url) {
    return (
      <Button variant="outline" size="sm" onClick={load}>
        {file.name}
      </Button>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element -- signed cross-origin URL
    <img src={url} alt={file.name} className="max-h-96 rounded-lg border" />
  );
}
