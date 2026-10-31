"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  ChevronRight,
  Eye,
  Loader2,
  Pencil,
  RefreshCw,
  Search,
  ShieldAlert,
  Trash2,
  X
} from "lucide-react";
import { useTranslations } from "use-intl";
import { useMemo, useRef, useState } from "react";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { useFocusRescue } from "@/lib/focus-rescue";
import { invalidateSpaces } from "@/features/spaces/space";
import { EmptyState } from "@/components/composites/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import { matchesSearch, searchTerms } from "@/lib/search";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import {
  approveAllToolChanges,
  approveToolChanges,
  MCP_KEY,
  mcpServerToolsQueryOptions,
  mcpToolsKey,
  type McpServerTool,
  type McpServer,
  rejectToolChanges,
  syncMcpServerTools,
  updateTenantToolEnabled
} from "../mcp";
import { readableParams, toolRisk } from "../mcp-helpers";
import { ToolNameEditor } from "./tool-name-editor";
import { PendingToolView } from "./pending-tool-view";

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
  serverId,
  onRenamed,
  tool,
  busy,
  onToggle
}: {
  tool: McpServerTool;
  serverId: string;
  onRenamed: () => void;
  /** Its own toggle is saving. */
  busy: boolean;
  onToggle: (enabled: boolean) => void;
}) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  return (
    <Collapsible open={open} onOpenChange={setOpen} className="border-border rounded-lg border">
      <div className="flex items-center gap-3 p-3">
        <CollapsibleTrigger className="flex min-w-0 flex-1 items-center gap-2 text-left">
          <ChevronRight
            className={cn("size-4 shrink-0 transition-transform", open && "rotate-90")}
            aria-hidden="true"
          />
          <span className="min-w-0">
            <span className="block truncate text-sm font-medium">
              {tool.display_name || tool.title || tool.name}
            </span>
            {(tool.display_name || tool.title) && (
              <span className="text-muted-foreground block truncate font-mono text-xs">
                {tool.name}
              </span>
            )}
          </span>
          <RiskChip tool={tool} />
        </CollapsibleTrigger>
        <Switch
          checked={tool.is_enabled_by_default}
          aria-busy={busy || undefined}
          aria-label={t("mcp_activate_tool", { name: tool.name })}
          onCheckedChange={onToggle}
        />
      </div>
      <div className="px-3 pb-3">
        <ToolNameEditor serverId={serverId} tool={tool} onSaved={onRenamed} />
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
  serverId,
  tool,
  busy,
  onApprove,
  onReject
}: {
  tool: McpServerTool;
  serverId: string;
  /** Which of its decisions is being saved. */
  busy: "approve" | "reject" | null;
  onApprove: () => void;
  onReject: () => void;
}) {
  const t = useTranslations();
  const descriptionChanged =
    tool.pending_description != null && tool.pending_description !== tool.description;
  const schemaChanged =
    tool.pending_input_schema != null &&
    JSON.stringify(tool.pending_input_schema) !== JSON.stringify(tool.input_schema);
  const pendingView =
    !tool.removed_from_remote &&
    Boolean(tool.pending_ui_resource_sha256) &&
    tool.pending_ui_resource_sha256 !== tool.ui_resource_sha256;
  const changed =
    !tool.removed_from_remote &&
    (descriptionChanged || schemaChanged || (pendingView && Boolean(tool.ui_resource_sha256)));
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

          {descriptionChanged && !tool.removed_from_remote ? (
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
          {pendingView && <PendingToolView serverId={serverId} tool={tool} />}
        </div>

        <div className="flex shrink-0 items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="size-7"
            aria-busy={busy === "approve" || undefined}
            onClick={onApprove}
            aria-label={`${t("approve")} ${tool.name}`}
          >
            {busy === "approve" ? (
              <Loader2 className="size-4 motion-safe:animate-spin" aria-hidden="true" />
            ) : (
              <Check className="text-success size-4" />
            )}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="size-7"
            aria-busy={busy === "reject" || undefined}
            onClick={onReject}
            aria-label={`${t("reject")} ${tool.name}`}
          >
            {busy === "reject" ? (
              <Loader2 className="size-4 motion-safe:animate-spin" aria-hidden="true" />
            ) : (
              <X className="text-destructive size-4" />
            )}
          </Button>
        </div>
      </div>
    </li>
  );
}

export function ToolsTab({
  server
}: {
  server: Pick<McpServer, "id" | "purpose" | "http_auth_type">;
}) {
  const serverId = server.id;
  const readOnly = server.http_auth_type === "internal";
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");

  const query = useQuery(mcpServerToolsQueryOptions(browserApi, serverId));
  const tools = query.data;
  const heading = useRef<HTMLHeadingElement>(null);
  const rescue = useFocusRescue();

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
      const results = await Promise.allSettled(
        targets.map((tool) => updateTenantToolEnabled(browserApi, tool.id, enabled))
      );
      const failure = results.find((result) => result.status === "rejected");
      if (failure?.status === "rejected") throw failure.reason;
    },
    onSettled: invalidate,
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

  // One change at a time, as before; the control whose change is saving shows
  // it (aria-busy) and keeps focus, and presses while one runs are ignored.
  const busy = sync.isPending || toggle.isPending || bulkToggle.isPending || review.isPending;
  const [running, setRunning] = useState<string | null>(null);
  const settle = { onSettled: () => setRunning(null) };
  function run(control: string, start: () => void) {
    if (busy || running !== null) return;
    setRunning(control);
    start();
  }
  const busyOn = (control: string) => running === control || undefined;

  const pending = useMemo(() => (tools ?? []).filter((tool) => tool.requires_approval), [tools]);
  const active = useMemo(() => (tools ?? []).filter((tool) => !tool.requires_approval), [tools]);
  const filteredActive = useMemo(() => {
    if (searchTerms(search).length === 0) return active;
    return active.filter((tool) =>
      matchesSearch([tool.name, tool.display_name, tool.title, tool.description], search)
    );
  }, [active, search]);

  const enabledCount = active.filter((tool) => tool.is_enabled_by_default).length;
  const percent = active.length === 0 ? 0 : Math.round((enabledCount / active.length) * 100);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <h2 ref={heading} tabIndex={-1} className="text-base font-semibold">
          {t("mcp_server_tools")}
        </h2>
        {!readOnly && (
          <Button
            variant="outline"
            size="sm"
            aria-busy={sync.isPending || undefined}
            onClick={() => run("sync", () => sync.mutate(undefined, settle))}
          >
            {!sync.isPending && <RefreshCw className="size-4" />}
            {sync.isPending ? t("syncing") : t("sync_tools")}
          </Button>
        )}
      </div>

      <QueryStateBoundary query={query} rows={1} height={160}>
        {(loaded) =>
          loaded.length === 0 ? (
            <EmptyState
              title={t("no_tools_found")}
              description={readOnly ? undefined : t("click_sync_to_discover_tools")}
            />
          ) : readOnly ? (
            <ul className="flex flex-col gap-3" aria-label={t("mcp_available_tools_aria")}>
              {loaded.map((tool) => {
                const imageTool =
                  server.purpose === "image_generation" && tool.name === "generate_image";
                const title =
                  tool.display_name ??
                  (imageTool ? t("tool_generate_image_title") : (tool.title ?? tool.name));
                const description = imageTool
                  ? t("tool_generate_image_description")
                  : tool.description?.split(/\n\s*\n/)[0];
                return (
                  <li
                    key={tool.id}
                    className="border-border flex flex-wrap items-start justify-between gap-3 rounded-lg border p-3"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium">{title}</p>
                      {title !== tool.name && (
                        <p className="text-muted-foreground font-mono text-xs break-all">
                          {tool.name}
                        </p>
                      )}
                      {description && (
                        <p className="text-muted-foreground mt-1 text-sm">{description}</p>
                      )}
                    </div>
                    <Badge>{t(tool.is_enabled_by_default ? "enabled" : "disabled")}</Badge>
                  </li>
                );
              })}
            </ul>
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
                        aria-busy={busyOn("approve-all")}
                        onClick={() =>
                          run("approve-all", () => review.mutate({ kind: "approve-all" }, settle))
                        }
                      >
                        {!busyOn("approve-all") && <Check className="size-3.5" />}{" "}
                        {t("approve_all")}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        aria-busy={busyOn("reject-all")}
                        onClick={() =>
                          run("reject-all", () =>
                            review.mutate(
                              { kind: "reject", toolIds: pending.map((tool) => tool.id) },
                              settle
                            )
                          )
                        }
                      >
                        {!busyOn("reject-all") && <X className="size-3.5" />} {t("reject_all")}
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
                        serverId={serverId}
                        tool={tool}
                        busy={
                          busyOn(`approve:${tool.id}`)
                            ? "approve"
                            : busyOn(`reject:${tool.id}`)
                              ? "reject"
                              : null
                        }
                        onApprove={() =>
                          run(`approve:${tool.id}`, () =>
                            review.mutate({ kind: "approve", toolIds: [tool.id] }, settle)
                          )
                        }
                        onReject={() =>
                          run(`reject:${tool.id}`, () =>
                            review.mutate({ kind: "reject", toolIds: [tool.id] }, settle)
                          )
                        }
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
                        aria-busy={busyOn("all-on")}
                        onClick={() => run("all-on", () => bulkToggle.mutate(true, settle))}
                      >
                        {t("mcp_all_on")}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-busy={busyOn("all-off")}
                        onClick={() => run("all-off", () => bulkToggle.mutate(false, settle))}
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
                            serverId={serverId}
                            onRenamed={() => {
                              rescue(heading.current);
                              invalidate();
                              void invalidateSpaces(queryClient);
                            }}
                            tool={tool}
                            busy={busyOn(`toggle:${tool.id}`) ?? false}
                            onToggle={(checked) =>
                              run(`toggle:${tool.id}`, () =>
                                toggle.mutate({ toolId: tool.id, isEnabled: checked }, settle)
                              )
                            }
                          />
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </>
          )
        }
      </QueryStateBoundary>
    </div>
  );
}
