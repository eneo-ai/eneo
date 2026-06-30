"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  ChevronRight,
  Eye,
  Pencil,
  RefreshCw,
  Search,
  ShieldAlert,
  Trash2,
  X
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { EmptyState } from "@/components/composites/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import { cn } from "@/lib/utils";
import {
  approveAllToolChanges,
  approveToolChanges,
  MCP_KEY,
  mcpServerToolsQueryOptions,
  mcpToolsKey,
  type McpServerTool,
  rejectToolChanges,
  syncMcpServerTools,
  updateTenantToolEnabled
} from "../mcp";
import { readableParams, toolRisk } from "../mcp-helpers";

function RiskChip({ tool }: { tool: McpServerTool }) {
  const t = useTranslations();
  const risk = toolRisk(tool);
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Badge
          className={cn(
            "gap-1 font-normal",
            risk === "write"
              ? "border-warning/30 bg-warning/15 text-warning"
              : "border-success/30 bg-success/15 text-success"
          )}
        >
          {risk === "write" ? (
            <Pencil className="size-3" aria-hidden="true" />
          ) : (
            <Eye className="size-3" aria-hidden="true" />
          )}
          {risk === "write" ? t("mcp_risk_write") : t("mcp_risk_read")}
        </Badge>
      </TooltipTrigger>
      <TooltipContent>{t("mcp_risk_heuristic_hint")}</TooltipContent>
    </Tooltip>
  );
}

function ParamList({ schema }: { schema: McpServerTool["input_schema"] }) {
  const t = useTranslations();
  const params = readableParams(schema);
  if (params.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("mcp_no_parameters")}</p>;
  }
  return (
    <dl className="flex flex-col gap-2">
      {params.map((param) => (
        <div key={param.name} className="flex flex-col gap-0.5">
          <dt className="flex flex-wrap items-baseline gap-2">
            <span className="font-mono text-sm">{param.name}</span>
            <span className="text-muted-foreground text-xs">{param.type}</span>
            {param.required && <span className="text-warning text-xs">{t("mcp_required")}</span>}
          </dt>
          {param.description && (
            <dd className="text-muted-foreground text-xs">{param.description}</dd>
          )}
        </div>
      ))}
    </dl>
  );
}

function ActiveToolRow({
  tool,
  disabled,
  onToggle
}: {
  tool: McpServerTool;
  disabled: boolean;
  onToggle: (enabled: boolean) => void;
}) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  return (
    <Collapsible
      open={open}
      onOpenChange={setOpen}
      className={cn("border-border rounded-lg border", !tool.is_enabled_by_default && "opacity-60")}
    >
      <div className="flex items-center gap-3 p-3">
        <CollapsibleTrigger className="flex min-w-0 flex-1 items-center gap-2 text-left">
          <ChevronRight
            className={cn("size-4 shrink-0 transition-transform", open && "rotate-90")}
            aria-hidden="true"
          />
          <span className="min-w-0">
            <span className="block truncate text-sm font-medium">{tool.title || tool.name}</span>
            {tool.title && (
              <span className="text-muted-foreground block truncate font-mono text-xs">
                {tool.name}
              </span>
            )}
          </span>
          <RiskChip tool={tool} />
        </CollapsibleTrigger>
        <Switch
          checked={tool.is_enabled_by_default}
          disabled={disabled}
          aria-label={t("mcp_activate_tool", { name: tool.name })}
          onCheckedChange={onToggle}
        />
      </div>
      <CollapsibleContent className="border-t px-3 py-3">
        {tool.description && (
          <p className="text-muted-foreground mb-3 text-sm">{tool.description}</p>
        )}
        <ParamList schema={tool.input_schema} />
      </CollapsibleContent>
    </Collapsible>
  );
}

function PendingToolRow({
  tool,
  disabled,
  onApprove,
  onReject
}: {
  tool: McpServerTool;
  disabled: boolean;
  onApprove: () => void;
  onReject: () => void;
}) {
  const t = useTranslations();
  const changed = !tool.removed_from_remote && Boolean(tool.pending_description);
  return (
    <li className="border-warning/30 bg-warning/10 rounded-lg border p-3">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate font-mono text-sm font-medium">{tool.name}</span>
            {tool.removed_from_remote ? (
              <span className="text-destructive inline-flex items-center gap-1 text-xs font-medium">
                <Trash2 className="size-3" aria-hidden="true" />
                {t("removed_from_server")}
              </span>
            ) : changed ? (
              <Badge className="border-warning/30 bg-warning/15 text-warning gap-1 font-normal">
                {t("mcp_change_changed")}
              </Badge>
            ) : (
              <Badge className="border-success/30 bg-success/15 text-success gap-1 font-normal">
                {t("mcp_change_new")}
              </Badge>
            )}
          </div>

          {changed ? (
            <div className="mt-2 space-y-1.5">
              {tool.description && (
                <div className="bg-secondary rounded px-2.5 py-1.5">
                  <span className="text-muted-foreground mb-0.5 block text-[10px] font-medium tracking-wider uppercase">
                    {t("current_description")}
                  </span>
                  <p className="text-muted-foreground text-xs leading-snug">{tool.description}</p>
                </div>
              )}
              <div className="border-warning/30 bg-warning/15 rounded border px-2.5 py-1.5">
                <span className="text-warning mb-0.5 block text-[10px] font-medium tracking-wider uppercase">
                  {t("new_description")}
                </span>
                <p className="text-warning text-xs leading-snug">{tool.pending_description}</p>
              </div>
            </div>
          ) : (
            tool.description && (
              <p
                className={cn(
                  "text-muted-foreground mt-1 text-xs leading-snug",
                  tool.removed_from_remote && "line-through"
                )}
              >
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
            <Check className="text-success size-4" />
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

export function ToolsTab({ serverId }: { serverId: string }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");

  const { data: tools, isPending } = useQuery(mcpServerToolsQueryOptions(browserApi, serverId));

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: mcpToolsKey(serverId) });
    void queryClient.invalidateQueries({ queryKey: MCP_KEY });
  };

  const sync = useMutation({
    mutationFn: () => syncMcpServerTools(browserApi, serverId),
    onSuccess: (result) => {
      invalidate();
      const found =
        (result.new_tools?.length ?? 0) +
        (result.changed_tools?.length ?? 0) +
        (result.removed_tools?.length ?? 0);
      toast.success(found > 0 ? t("mcp_sync_pending", { count: found }) : t("mcp_sync_clean"));
    },
    onError: (error) => toastApiError(error, t)
  });

  const toggle = useMutation({
    mutationFn: ({ toolId, isEnabled }: { toolId: string; isEnabled: boolean }) =>
      updateTenantToolEnabled(browserApi, toolId, isEnabled),
    onSuccess: invalidate,
    onError: (error) => toastApiError(error, t)
  });

  const bulkToggle = useMutation({
    mutationFn: async (enabled: boolean) => {
      const targets = (tools ?? []).filter(
        (tool) => !tool.requires_approval && tool.is_enabled_by_default !== enabled
      );
      await Promise.allSettled(
        targets.map((tool) => updateTenantToolEnabled(browserApi, tool.id, enabled))
      );
    },
    onSuccess: invalidate,
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
    onSuccess: invalidate,
    onError: (error) => toastApiError(error, t)
  });

  const busy = sync.isPending || toggle.isPending || bulkToggle.isPending || review.isPending;

  const pending = useMemo(() => (tools ?? []).filter((tool) => tool.requires_approval), [tools]);
  const active = useMemo(() => (tools ?? []).filter((tool) => !tool.requires_approval), [tools]);
  const filteredActive = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return active;
    return active.filter((tool) =>
      [tool.name, tool.title ?? "", tool.description ?? ""].join(" ").toLowerCase().includes(query)
    );
  }, [active, search]);

  const enabledCount = active.filter((tool) => tool.is_enabled_by_default).length;
  const percent = active.length === 0 ? 0 : Math.round((enabledCount / active.length) * 100);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-base font-semibold">{t("mcp_server_tools")}</h2>
        <Button variant="outline" size="sm" disabled={sync.isPending} onClick={() => sync.mutate()}>
          <RefreshCw className={sync.isPending ? "size-4 animate-spin" : "size-4"} />
          {sync.isPending ? t("syncing") : t("sync_tools")}
        </Button>
      </div>

      {isPending ? (
        <Skeleton className="h-40 w-full" />
      ) : !tools || tools.length === 0 ? (
        <EmptyState title={t("no_tools_found")} description={t("click_sync_to_discover_tools")} />
      ) : (
        <>
          {pending.length > 0 && (
            <Card className="border-warning/30 gap-3 p-4">
              <div className="flex items-center justify-between gap-2">
                <span className="text-warning flex items-center gap-2 text-sm font-medium">
                  <ShieldAlert className="size-4 shrink-0" aria-hidden="true" />
                  {t("mcp_review_inbox_title", { count: pending.length })}
                </span>
                <div className="flex shrink-0 items-center gap-1.5">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy}
                    onClick={() => review.mutate({ kind: "approve-all" })}
                  >
                    <Check className="size-3.5" /> {t("approve_all")}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy}
                    onClick={() =>
                      review.mutate({ kind: "reject", toolIds: pending.map((tool) => tool.id) })
                    }
                  >
                    <X className="size-3.5" /> {t("reject_all")}
                  </Button>
                </div>
              </div>
              <p className="text-muted-foreground text-sm">
                {t("tool_uses_previous_until_approved")}
              </p>
              <ul className="flex flex-col gap-2">
                {pending.map((tool) => (
                  <PendingToolRow
                    key={tool.id}
                    tool={tool}
                    disabled={busy}
                    onApprove={() => review.mutate({ kind: "approve", toolIds: [tool.id] })}
                    onReject={() => review.mutate({ kind: "reject", toolIds: [tool.id] })}
                  />
                ))}
              </ul>
            </Card>
          )}

          {active.length > 0 && (
            <div className="flex flex-col gap-3">
              <div className="relative">
                <Search
                  className="text-muted-foreground absolute top-1/2 left-2.5 size-4 -translate-y-1/2"
                  aria-hidden="true"
                />
                <Input
                  className="pl-8"
                  placeholder={t("mcp_search_tools")}
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  aria-label={t("mcp_search_tools")}
                />
              </div>

              <div className="flex items-center gap-3">
                <Progress value={percent} className="flex-1" />
                <span className="text-muted-foreground shrink-0 text-sm tabular-nums">
                  {t("mcp_tools_enabled_of", { enabled: enabledCount, total: active.length })}
                </span>
                <div className="flex shrink-0 items-center gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() => bulkToggle.mutate(true)}
                  >
                    {t("mcp_all_on")}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() => bulkToggle.mutate(false)}
                  >
                    {t("mcp_all_off")}
                  </Button>
                </div>
              </div>

              {filteredActive.length === 0 ? (
                <p className="text-muted-foreground py-6 text-center text-sm">
                  {t("mcp_no_match")}
                </p>
              ) : (
                <ul className="flex flex-col gap-2" aria-label={t("mcp_available_tools_aria")}>
                  {filteredActive.map((tool) => (
                    <li key={tool.id}>
                      <ActiveToolRow
                        tool={tool}
                        disabled={busy}
                        onToggle={(checked) =>
                          toggle.mutate({ toolId: tool.id, isEnabled: checked })
                        }
                      />
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
