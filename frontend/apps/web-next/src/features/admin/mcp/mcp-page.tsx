"use client";

import { useMutation, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import {
  ChevronRight,
  Lock,
  MoreHorizontal,
  Plus,
  Search,
  Settings2,
  ShieldAlert,
  Trash2,
  Wrench
} from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { EmptyState } from "@/components/composites/empty-state";
import { PageHeader } from "@/components/composites/page-header";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { securityClassificationsQueryOptions } from "@/features/admin/security-classifications/security-classifications";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import { cn } from "@/lib/utils";
import { McpServerDialog } from "./mcp-dialog";
import { hostFromUrl, initials, isQuarantined, pendingTools } from "./mcp-helpers";
import {
  deleteMcpServer,
  MCP_KEY,
  mcpServersQueryOptions,
  setMcpOrgEnabled,
  type McpServer
} from "./mcp";

type Filter = "all" | "attention" | "enabled" | "disabled";

function StatTile({
  label,
  value,
  tone = "default",
  active = false,
  onClick
}: {
  label: string;
  value: number;
  tone?: "default" | "warning";
  active?: boolean;
  onClick?: () => void;
}) {
  const body = (
    <>
      <span
        className={cn("text-sm", tone === "warning" ? "text-warning" : "text-muted-foreground")}
      >
        {label}
      </span>
      <span
        className={cn("text-2xl font-semibold tabular-nums", tone === "warning" && "text-warning")}
      >
        {value}
      </span>
    </>
  );

  const className = cn(
    "flex flex-col gap-0.5 rounded-xl px-4 py-3 text-left transition-colors",
    tone === "warning" ? "bg-warning/10" : "bg-muted/50",
    onClick &&
      "hover:bg-warning/15 focus-visible:ring-ring focus-visible:ring-2 focus-visible:outline-none",
    active && "ring-warning ring-2"
  );

  if (onClick) {
    return (
      <button type="button" onClick={onClick} aria-pressed={active} className={className}>
        {body}
      </button>
    );
  }
  return <div className={className}>{body}</div>;
}

function McpServerCard({
  server,
  securityEnabled
}: {
  server: McpServer;
  securityEnabled: boolean;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [showDelete, setShowDelete] = useState(false);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: MCP_KEY });
  const tools = server.tools ?? [];
  const pending = pendingTools(tools).length;
  const quarantined = isQuarantined(server, securityEnabled);
  const detailHref = `/admin/mcp-servers/${server.id}`;
  const host = hostFromUrl(server.http_url);
  const quarantineId = `mcp-quarantine-${server.id}`;

  const setEnabled = useMutation({
    mutationFn: (next: boolean) => setMcpOrgEnabled(browserApi, server.id, next),
    onSuccess: invalidate,
    onError: (error) => toastApiError(error, t)
  });

  const remove = useMutation({
    mutationFn: () => deleteMcpServer(browserApi, server.id),
    onSuccess: () => {
      invalidate();
      setShowDelete(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  // Quarantine: an unclassified server can't be enabled while classifications
  // are enforced. An already-enabled one stays toggleable so it can be turned off.
  const toggleBlocked = quarantined && !server.is_org_enabled;

  return (
    <Card className="gap-0 overflow-hidden p-0">
      <div className="flex items-center gap-3 px-4 py-3.5">
        <Avatar className="size-9 rounded-md">
          {server.icon_url ? <AvatarImage src={server.icon_url} alt="" /> : null}
          <AvatarFallback className="rounded-md text-xs font-medium">
            {initials(server.name)}
          </AvatarFallback>
        </Avatar>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Link href={detailHref} className="font-medium hover:underline">
              {server.name}
            </Link>
            {securityEnabled &&
              (server.security_classification ? (
                <Badge
                  variant="outline"
                  className="border-border text-muted-foreground gap-1 font-normal"
                >
                  <Lock className="size-3" aria-hidden="true" />
                  {server.security_classification.name}
                </Badge>
              ) : (
                <Badge className="border-warning/30 bg-warning/15 text-warning gap-1 font-normal">
                  <ShieldAlert className="size-3" aria-hidden="true" />
                  {t("mcp_unclassified")}
                </Badge>
              ))}
          </div>
          <div className="text-muted-foreground mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs">
            <Link
              href={`${detailHref}?tab=tools`}
              className="inline-flex items-center gap-1 hover:underline"
            >
              <Wrench className="size-3.5" aria-hidden="true" />
              {t("mcp_tools_count", { count: server.tools_count })}
            </Link>
            {host && <span className="truncate font-mono">{host}</span>}
          </div>
        </div>

        <Tooltip>
          <TooltipTrigger asChild>
            <span className="inline-flex">
              <Switch
                checked={server.is_org_enabled}
                disabled={setEnabled.isPending || toggleBlocked}
                aria-label={t("mcp_toggle_server", { name: server.name })}
                aria-describedby={toggleBlocked ? quarantineId : undefined}
                onCheckedChange={(checked) => setEnabled.mutate(checked)}
              />
            </span>
          </TooltipTrigger>
          <TooltipContent>
            {toggleBlocked
              ? t("mcp_quarantine_blocks_enable")
              : server.is_org_enabled
                ? t("mcp_toggle_to_disable")
                : t("mcp_toggle_to_enable")}
          </TooltipContent>
        </Tooltip>

        <Button
          asChild
          variant="ghost"
          size="icon"
          aria-label={t("mcp_manage_server", { name: server.name })}
        >
          <Link href={detailHref}>
            <ChevronRight className="size-4" />
          </Link>
        </Button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label={t("actions")}>
              <MoreHorizontal className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem asChild>
              <Link href={detailHref}>
                <Settings2 className="size-4" /> {t("mcp_manage")}
              </Link>
            </DropdownMenuItem>
            <DropdownMenuItem asChild>
              <Link href={`${detailHref}?tab=tools`}>
                <Wrench className="size-4" /> {t("mcp_server_tools")}
              </Link>
            </DropdownMenuItem>
            <DropdownMenuItem variant="destructive" onSelect={() => setShowDelete(true)}>
              <Trash2 className="size-4" /> {t("delete")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {toggleBlocked && (
        <p
          id={quarantineId}
          className="bg-warning/10 text-warning flex items-center gap-2 border-t px-4 py-2 text-sm"
        >
          <ShieldAlert className="size-4 shrink-0" aria-hidden="true" />
          {t("mcp_quarantine_strip")}
          <Link
            href={`${detailHref}?tab=security`}
            className="ml-auto shrink-0 font-medium hover:underline"
          >
            {t("mcp_classify")}
          </Link>
        </p>
      )}

      {pending > 0 && (
        <Link
          href={`${detailHref}?tab=tools`}
          className="bg-warning/10 text-warning hover:bg-warning/15 flex items-center gap-2 border-t px-4 py-2 text-sm"
        >
          <ShieldAlert className="size-4 shrink-0" aria-hidden="true" />
          {t("mcp_pending_review_strip", { count: pending })}
          <ChevronRight className="ml-auto size-4 shrink-0" aria-hidden="true" />
        </Link>
      )}

      <ConfirmDialogControlled
        open={showDelete}
        onOpenChange={setShowDelete}
        title={t("delete_mcp_server")}
        description={t("confirm_delete_mcp_server", { name: server.name })}
        confirmLabel={remove.isPending ? t("deleting") : t("delete")}
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </Card>
  );
}

const FILTERS: Filter[] = ["all", "attention", "enabled", "disabled"];

export function McpServersPage() {
  const t = useTranslations();
  const { data: servers } = useSuspenseQuery(mcpServersQueryOptions(browserApi));
  const { data: security } = useSuspenseQuery(securityClassificationsQueryOptions(browserApi));
  const securityEnabled = security.security_enabled;
  const [showAdd, setShowAdd] = useState(false);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("all");

  const needsAttention = (server: McpServer) =>
    pendingTools(server.tools ?? []).length > 0 || isQuarantined(server, securityEnabled);

  const totals = useMemo(() => {
    let enabled = 0;
    let tools = 0;
    let pending = 0;
    for (const server of servers) {
      if (server.is_org_enabled) enabled += 1;
      tools += server.tools_count;
      pending += pendingTools(server.tools ?? []).length;
    }
    return { enabled, tools, pending };
  }, [servers]);

  const visible = useMemo(() => {
    const query = search.trim().toLowerCase();
    return servers.filter((server) => {
      if (filter === "enabled" && !server.is_org_enabled) return false;
      if (filter === "disabled" && server.is_org_enabled) return false;
      if (filter === "attention" && !needsAttention(server)) return false;
      if (!query) return true;
      const haystack = [server.name, server.http_url, ...(server.tags ?? [])]
        .join(" ")
        .toLowerCase();
      return haystack.includes(query);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [servers, search, filter, securityEnabled]);

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <PageHeader title={t("mcp_servers")}>
        <Button onClick={() => setShowAdd(true)}>
          <Plus className="size-4" /> {t("add_mcp_server")}
        </Button>
      </PageHeader>

      {servers.length === 0 ? (
        <EmptyState
          title={t("no_mcp_servers_available")}
          description={t("add_mcp_server_to_get_started")}
        />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatTile label={t("mcp_stat_servers")} value={servers.length} />
            <StatTile label={t("mcp_stat_enabled")} value={totals.enabled} />
            <StatTile label={t("mcp_stat_tools")} value={totals.tools} />
            <StatTile
              label={t("mcp_stat_pending")}
              value={totals.pending}
              tone="warning"
              active={filter === "attention"}
              onClick={
                totals.pending > 0
                  ? () => setFilter(filter === "attention" ? "all" : "attention")
                  : undefined
              }
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-48 flex-1">
              <Search
                className="text-muted-foreground absolute top-1/2 left-2.5 size-4 -translate-y-1/2"
                aria-hidden="true"
              />
              <Input
                className="pl-8"
                placeholder={t("mcp_search_placeholder")}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                aria-label={t("mcp_search_placeholder")}
              />
            </div>
            <div
              className="flex items-center gap-1 rounded-lg border p-0.5"
              role="group"
              aria-label={t("filter")}
            >
              {FILTERS.map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setFilter(value)}
                  aria-pressed={filter === value}
                  className={cn(
                    "rounded-md px-2.5 py-1 text-sm transition-colors",
                    filter === value
                      ? "bg-accent text-accent-foreground"
                      : "text-muted-foreground hover:text-foreground"
                  )}
                >
                  {t(`mcp_filter_${value}`)}
                </button>
              ))}
            </div>
          </div>

          {visible.length === 0 ? (
            <p className="text-muted-foreground py-10 text-center text-sm">{t("mcp_no_match")}</p>
          ) : (
            <div className="flex flex-col gap-3" role="list">
              {visible.map((server) => (
                <div role="listitem" key={server.id}>
                  <McpServerCard server={server} securityEnabled={securityEnabled} />
                </div>
              ))}
            </div>
          )}
        </>
      )}

      <McpServerDialog open={showAdd} onOpenChange={setShowAdd} />
    </div>
  );
}
