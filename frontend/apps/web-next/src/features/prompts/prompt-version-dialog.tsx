"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { formatDateTime } from "@/lib/format";

type PromptResource = {
  type: "assistant" | "app";
  id: string;
};

async function fetchPromptVersions(resource: PromptResource) {
  if (resource.type === "assistant") {
    return (
      await unwrap(
        browserApi.GET("/api/v1/assistants/{id}/prompts/", {
          params: { path: { id: resource.id } }
        })
      )
    ).items;
  }

  return (
    await unwrap(
      browserApi.GET("/api/v1/apps/{id}/prompts/", {
        params: { path: { id: resource.id } }
      })
    )
  ).items;
}

/** Browse a resource's prompt history and load a past version for review. */
export function PromptVersionDialog({
  resource,
  open,
  onOpenChange,
  onUseVersion
}: {
  resource: PromptResource;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUseVersion: (text: string) => void;
}) {
  const t = useTranslations();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const list = useQuery({
    queryKey: [resource.type, resource.id, "prompts"],
    enabled: open,
    queryFn: () => fetchPromptVersions(resource)
  });

  const preview = useQuery({
    queryKey: ["prompt", selectedId],
    enabled: open && Boolean(selectedId),
    queryFn: () =>
      unwrap(
        browserApi.GET("/api/v1/prompts/{id}/", {
          params: { path: { id: selectedId as string } }
        })
      )
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-hidden sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t("prompt_history")}</DialogTitle>
        </DialogHeader>
        <div className="grid max-h-[60vh] grid-cols-1 gap-4 sm:grid-cols-[18rem_1fr]">
          <div className="overflow-y-auto rounded-md border">
            {list.isPending ? (
              <Skeleton className="h-40 w-full" />
            ) : (
              <ul className="divide-border divide-y">
                {(list.data ?? []).map((version) => (
                  <li key={version.id}>
                    <button
                      type="button"
                      className={`hover:bg-muted/50 flex w-full flex-col items-start gap-0.5 px-3 py-2 text-left ${
                        selectedId === version.id ? "bg-accent" : ""
                      }`}
                      onClick={() => setSelectedId(version.id)}
                    >
                      <span className="flex items-center gap-2 text-sm">
                        {version.created_at
                          ? formatDateTime(version.created_at)
                          : version.id.slice(0, 8)}
                        {version.is_selected && (
                          <Badge variant="secondary">{t("current_version")}</Badge>
                        )}
                      </span>
                      {version.description && (
                        <span className="text-muted-foreground truncate text-xs">
                          {version.description}
                        </span>
                      )}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="flex min-h-0 flex-col gap-2">
            <div className="bg-muted/30 flex-1 overflow-y-auto rounded-md border p-3">
              {!selectedId ? (
                <p className="text-muted-foreground text-sm">{t("preview")}</p>
              ) : preview.isPending ? (
                <Skeleton className="h-40 w-full" />
              ) : (
                <pre className="text-sm whitespace-pre-wrap">{preview.data?.text}</pre>
              )}
            </div>
            <Button
              className="w-fit self-end"
              disabled={!preview.data?.text}
              onClick={() => {
                if (preview.data?.text) {
                  onUseVersion(preview.data.text);
                  onOpenChange(false);
                }
              }}
            >
              {t("use_this_version")}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
