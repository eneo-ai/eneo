"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { EmptyState } from "@/components/composites/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import { mcpServerToolsQueryOptions, mcpToolsKey, syncMcpServerTools } from "./mcp";

/** Read-only catalog of an MCP server's tools, with a remote re-sync. */
export function McpToolsDialog({
  serverId,
  serverName,
  open,
  onOpenChange
}: {
  serverId: string;
  serverName: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const { data: tools, isPending } = useQuery({
    ...mcpServerToolsQueryOptions(browserApi, serverId),
    enabled: open
  });

  const sync = useMutation({
    mutationFn: () => syncMcpServerTools(browserApi, serverId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: mcpToolsKey(serverId) });
      toast.success(t("tools_synced"));
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("mcp_server_tools")}</DialogTitle>
          <DialogDescription>{serverName}</DialogDescription>
        </DialogHeader>

        <div className="flex justify-end">
          <Button
            variant="outline"
            size="sm"
            disabled={sync.isPending}
            onClick={() => sync.mutate()}
          >
            <RefreshCw className={sync.isPending ? "size-4 animate-spin" : "size-4"} />
            {t("sync_tools")}
          </Button>
        </div>

        {isPending ? (
          <Skeleton className="h-40 w-full" />
        ) : !tools || tools.length === 0 ? (
          <EmptyState title={t("no_tools_found")} />
        ) : (
          <ul className="flex flex-col gap-2">
            {tools.map((tool) => (
              <li key={tool.id} className="border-border flex flex-col gap-1 rounded-lg border p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-sm font-medium">{tool.name}</span>
                  {tool.is_enabled_by_default && (
                    <Badge variant="secondary">{t("enabled_by_default")}</Badge>
                  )}
                  {tool.requires_approval && (
                    <Badge variant="outline">{t("requires_approval")}</Badge>
                  )}
                  {tool.removed_from_remote && (
                    <Badge variant="destructive">{t("removed_from_remote")}</Badge>
                  )}
                </div>
                {tool.description && (
                  <p className="text-muted-foreground text-sm">{tool.description}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  );
}
