"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Check, RefreshCw, ShieldAlert, Trash2, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { EmptyState } from "@/components/composites/empty-state";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import {
  approveAllToolChanges,
  approveToolChanges,
  mcpServerToolsQueryOptions,
  mcpToolsKey,
  type McpServerTool,
  rejectToolChanges,
  syncMcpServerTools,
  updateTenantToolEnabled
} from "./mcp";

/** Admin governance for an MCP server's tools: per-tool enablement + remote tool-change review. */
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
  const invalidate = () => queryClient.invalidateQueries({ queryKey: mcpToolsKey(serverId) });

  const { data: tools, isPending } = useQuery({
    ...mcpServerToolsQueryOptions(browserApi, serverId),
    enabled: open
  });

  const sync = useMutation({
    mutationFn: () => syncMcpServerTools(browserApi, serverId),
    onSuccess: () => {
      void invalidate();
      toast.success(t("tools_synced"));
    },
    onError: (error) => toastApiError(error, t)
  });

  const toggle = useMutation({
    mutationFn: ({ toolId, isEnabled }: { toolId: string; isEnabled: boolean }) =>
      updateTenantToolEnabled(browserApi, toolId, isEnabled),
    onSuccess: () => void invalidate(),
    onError: (error) => toastApiError(error, t)
  });

  const bulkToggle = useMutation({
    mutationFn: async (enabled: boolean) => {
      const targets = (tools ?? []).filter((tool) => tool.is_enabled_by_default !== enabled);
      await Promise.allSettled(
        targets.map((tool) => updateTenantToolEnabled(browserApi, tool.id, enabled))
      );
    },
    onSuccess: () => void invalidate(),
    onError: (error) => toastApiError(error, t)
  });

  const review = useMutation({
    mutationFn: (
      args:
        | { kind: "approve"; toolIds: string[] }
        | { kind: "reject"; toolIds: string[] }
        | { kind: "approve-all" }
    ) => {
      if (args.kind === "approve") return approveToolChanges(browserApi, serverId, args.toolIds);
      if (args.kind === "reject") return rejectToolChanges(browserApi, serverId, args.toolIds);
      return approveAllToolChanges(browserApi, serverId);
    },
    onSuccess: () => void invalidate(),
    onError: (error) => toastApiError(error, t)
  });

  const pending = (tools ?? []).filter((tool) => tool.requires_approval);
  const enabledCount = (tools ?? []).filter((tool) => tool.is_enabled_by_default).length;
  const busy = sync.isPending || toggle.isPending || bulkToggle.isPending || review.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("mcp_server_tools")}</DialogTitle>
          <DialogDescription>{serverName}</DialogDescription>
        </DialogHeader>

        <div className="flex items-center justify-between">
          <span className="text-muted-foreground text-sm">
            {t("tools")} · {(tools ?? []).length}
            {pending.length > 0 && (
              <span className="ml-2 inline-flex items-center rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800 dark:bg-amber-950 dark:text-amber-300">
                {pending.length}{" "}
                {pending.length === 1 ? t("pending_update_singular") : t("pending_update_plural")}
              </span>
            )}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={sync.isPending}
            onClick={() => sync.mutate()}
          >
            <RefreshCw className={sync.isPending ? "size-4 animate-spin" : "size-4"} />
            {sync.isPending ? t("syncing") : t("sync_tools")}
          </Button>
        </div>

        {pending.length > 0 && (
          <div className="flex items-center justify-between gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 dark:border-amber-900 dark:bg-amber-950">
            <span className="flex items-center gap-2 text-sm font-medium text-amber-800 dark:text-amber-300">
              <ShieldAlert className="size-4 shrink-0" aria-hidden />
              {t("tool_uses_previous_until_approved")}
            </span>
            <div className="flex shrink-0 items-center gap-1.5">
              <Button
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() => review.mutate({ kind: "approve-all" })}
              >
                <Check className="size-3.5" />
                {t("approve_all")}
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() =>
                  review.mutate({ kind: "reject", toolIds: pending.map((tool) => tool.id) })
                }
              >
                <X className="size-3.5" />
                {t("reject_all")}
              </Button>
            </div>
          </div>
        )}

        {isPending ? (
          <Skeleton className="h-40 w-full" />
        ) : !tools || tools.length === 0 ? (
          <EmptyState title={t("no_tools_found")} description={t("click_sync_to_discover_tools")} />
        ) : (
          <>
            <div className="text-muted-foreground flex items-center justify-between text-xs">
              <span className="tracking-wider uppercase">
                {enabledCount} / {tools.length} {t("enabled").toLowerCase()}
              </span>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  className="hover:bg-accent rounded px-2 py-1 font-medium disabled:opacity-50"
                  disabled={busy}
                  onClick={() => bulkToggle.mutate(true)}
                >
                  {t("mcp_all_on")}
                </button>
                <span className="text-border">|</span>
                <button
                  type="button"
                  className="hover:bg-accent rounded px-2 py-1 font-medium disabled:opacity-50"
                  disabled={busy}
                  onClick={() => bulkToggle.mutate(false)}
                >
                  {t("mcp_all_off")}
                </button>
              </div>
            </div>

            <ul className="flex flex-col gap-2" aria-label={t("mcp_available_tools_aria")}>
              {tools.map((tool) =>
                tool.requires_approval ? (
                  <PendingToolRow
                    key={tool.id}
                    tool={tool}
                    t={t}
                    disabled={busy}
                    onApprove={() => review.mutate({ kind: "approve", toolIds: [tool.id] })}
                    onReject={() => review.mutate({ kind: "reject", toolIds: [tool.id] })}
                  />
                ) : (
                  <li
                    key={tool.id}
                    className={`border-border flex items-center gap-3 rounded-lg border p-3 ${
                      tool.is_enabled_by_default ? "" : "opacity-50"
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <span className="block truncate font-mono text-sm font-medium">
                        {tool.name}
                      </span>
                      {tool.description && (
                        <p
                          className="text-muted-foreground truncate text-xs"
                          title={tool.description}
                        >
                          {tool.description}
                        </p>
                      )}
                    </div>
                    <Switch
                      checked={tool.is_enabled_by_default}
                      disabled={busy}
                      onCheckedChange={(checked) =>
                        toggle.mutate({ toolId: tool.id, isEnabled: checked })
                      }
                      aria-label={t("mcp_activate_tool", { name: tool.name })}
                    />
                  </li>
                )
              )}
            </ul>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function PendingToolRow({
  tool,
  t,
  disabled,
  onApprove,
  onReject
}: {
  tool: McpServerTool;
  t: ReturnType<typeof useTranslations>;
  disabled: boolean;
  onApprove: () => void;
  onReject: () => void;
}) {
  return (
    <li className="rounded-lg border border-l-2 border-amber-200 border-l-amber-500 bg-amber-50 p-3 dark:border-amber-900 dark:bg-amber-950">
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="block truncate font-mono text-sm font-medium">{tool.name}</span>
            {tool.removed_from_remote ? (
              <span className="text-destructive inline-flex items-center gap-1 text-xs font-medium">
                <Trash2 className="size-3" />
                {t("removed_from_server")}
              </span>
            ) : (
              (tool.pending_description || tool.pending_input_schema) && (
                <span className="inline-flex items-center gap-1 text-xs font-medium text-amber-800 dark:text-amber-300">
                  <AlertTriangle className="size-3" />
                  {t("pending_description_change")}
                </span>
              )
            )}
          </div>

          {tool.pending_description && !tool.removed_from_remote ? (
            <div className="mt-2 space-y-1.5">
              {tool.description && (
                <div className="bg-secondary rounded px-2.5 py-1.5">
                  <span className="text-muted-foreground mb-0.5 block text-[10px] font-medium tracking-wider uppercase">
                    {t("current_description")}
                  </span>
                  <p className="text-muted-foreground text-xs leading-snug">{tool.description}</p>
                </div>
              )}
              <div className="rounded border border-amber-200 bg-amber-100 px-2.5 py-1.5 dark:border-amber-900 dark:bg-amber-900/40">
                <span className="mb-0.5 block text-[10px] font-medium tracking-wider text-amber-800 uppercase dark:text-amber-300">
                  {t("new_description")}
                </span>
                <p className="text-xs leading-snug text-amber-800 dark:text-amber-200">
                  {tool.pending_description}
                </p>
              </div>
            </div>
          ) : (
            tool.removed_from_remote &&
            tool.description && (
              <p className="text-muted-foreground mt-1 text-xs leading-snug line-through">
                {tool.description}
              </p>
            )
          )}
        </div>

        <div className="flex shrink-0 items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="size-7"
            disabled={disabled}
            onClick={onApprove}
            aria-label={`${t("approve")} ${tool.name}`}
          >
            <Check className="size-4 text-green-700 dark:text-green-400" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="size-7"
            disabled={disabled}
            onClick={onReject}
            aria-label={`${t("reject")} ${tool.name}`}
          >
            <X className="text-destructive size-4" />
          </Button>
        </div>
      </div>
    </li>
  );
}
