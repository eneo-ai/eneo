"use client";

import { useMutation, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { CheckCircle2, CircleDashed, Plus, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { PageHeader } from "@/components/composites/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CAPABILITIES, readinessKey, type Capability } from "@/features/capabilities/capabilities";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import {
  deleteMcpServer,
  MCP_KEY,
  mcpServersQueryOptions,
  setCapabilityProviderActive,
  type McpServer
} from "../mcp/mcp";
import { CapabilitySourceDialog } from "./capability-source-dialog";

export function CapabilityProvidersPage() {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const { data: servers } = useSuspenseQuery(mcpServersQueryOptions(browserApi));
  const [editing, setEditing] = useState<{ purpose: Capability; server: McpServer | null } | null>(
    null
  );
  const [deleting, setDeleting] = useState<McpServer | null>(null);
  const [notice, setNotice] = useState("");
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: MCP_KEY }),
      queryClient.invalidateQueries({ queryKey: ["spaces"] })
    ]);
  };
  const activate = useMutation({
    mutationFn: async ({ server, active }: { server: McpServer; active: boolean }) => {
      await setCapabilityProviderActive(browserApi, server.id, active);
    },
    onSuccess: () => {
      void invalidate().catch((cause) => toastApiError(cause, t));
    },
    onError: (cause) => toastApiError(cause, t)
  });
  const remove = useMutation({
    mutationFn: (server: McpServer) => deleteMcpServer(browserApi, server.id),
    onSuccess: () => {
      setDeleting(null);
      void invalidate().catch((cause) => toastApiError(cause, t));
    },
    onError: (cause) => toastApiError(cause, t)
  });

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 pb-16">
      <PageHeader title={t("tools")} tour="admin-tools">
        <Button asChild variant="outline">
          <Link href="/admin/mcp-servers">{t("mcp_servers")}</Link>
        </Button>
      </PageHeader>
      <p className="text-muted-foreground max-w-2xl text-sm">{t("tools_functions_description")}</p>
      {notice && (
        <p role="status" className="text-sm">
          {notice}
        </p>
      )}
      {CAPABILITIES.map((capability) => {
        const sources = servers
          .filter((server) => server.purpose === capability.purpose)
          .sort(
            (left, right) =>
              Number(left.audience === "groups") - Number(right.audience === "groups")
          );
        const activeDefault = sources.find(
          (server) => server.is_enabled && server.audience !== "groups"
        );
        return (
          <section
            key={capability.purpose}
            className="overflow-hidden rounded-xl border"
            aria-labelledby={`capability-${capability.purpose}`}
          >
            <header className="flex flex-wrap items-start justify-between gap-3 border-b p-5">
              <div className="flex items-start gap-3">
                <capability.icon className="text-primary mt-0.5 size-5" aria-hidden="true" />
                <div>
                  <h2 id={`capability-${capability.purpose}`} className="font-semibold">
                    {t(capability.purpose)}
                  </h2>
                  {!activeDefault && (
                    <p className="text-muted-foreground mt-1 text-sm">{t("tools_no_default")}</p>
                  )}
                </div>
              </div>
              <Button
                size="sm"
                onClick={() => setEditing({ purpose: capability.purpose, server: null })}
              >
                <Plus className="size-4" />
                {sources.length
                  ? t("tools_add_source")
                  : t("capability_configure", {
                      capability: t(capability.purpose).toLocaleLowerCase()
                    })}
              </Button>
            </header>
            {sources.length > 0 && (
              <ul className="divide-y">
                {sources.map((source) => {
                  const active = source.is_enabled === true;
                  const blocked = Boolean(source.readiness_reason);
                  return (
                    <li key={source.id} className="space-y-3 p-5">
                      <div className="flex flex-wrap items-start justify-between gap-4">
                        <div className="min-w-0 space-y-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="font-medium">{source.name}</h3>
                            {source.audience === "groups" && (
                              <Badge variant="outline">{t("tools_group_override")}</Badge>
                            )}
                          </div>
                          <p className="text-muted-foreground text-sm break-all">
                            {source.http_auth_type === "internal"
                              ? `${t("tools_source_model")} · ${source.image_model?.nickname || source.image_model?.name || t("tools_readiness_model_missing")}`
                              : `${t("tools_source_external")} · ${source.http_url}`}
                          </p>
                          {source.audience === "groups" && (
                            <p className="text-muted-foreground text-xs">
                              {(source.user_groups ?? []).map((group) => group.name).join(", ")}
                            </p>
                          )}
                        </div>
                        <Badge variant={blocked ? "destructive" : active ? "secondary" : "outline"}>
                          {blocked ? (
                            <TriangleAlert className="size-3" />
                          ) : active ? (
                            <CheckCircle2 className="size-3" />
                          ) : (
                            <CircleDashed className="size-3" />
                          )}
                          {t(
                            blocked ? "tools_blocked" : active ? "tools_active" : "tools_inactive"
                          )}
                        </Badge>
                      </div>
                      {blocked && (
                        <p className="text-warning text-sm">
                          {t(readinessKey(source.readiness_reason))}
                        </p>
                      )}
                      {!active && activeDefault && source.audience !== "groups" && (
                        <p className="text-muted-foreground text-xs">
                          {t("tools_replace_default", { name: activeDefault.name })}
                        </p>
                      )}
                      <div className="flex flex-wrap gap-2">
                        {/* Busy, it stays enabled so it keeps focus; while one source
                            changes, presses are ignored. */}
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={!active && blocked}
                          aria-busy={
                            (activate.isPending && activate.variables?.server.id === source.id) ||
                            undefined
                          }
                          onClick={() => {
                            if (!activate.isPending)
                              activate.mutate({ server: source, active: !active });
                          }}
                        >
                          {t(active ? "deactivate" : "activate")}
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() =>
                            setEditing({ purpose: capability.purpose, server: source })
                          }
                        >
                          {t("tools_change")}
                        </Button>
                        <Button size="sm" variant="ghost" asChild>
                          <Link href={`/admin/mcp-servers/${source.id}?tab=tools`}>
                            {t("mcp_server_tools")}
                          </Link>
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="text-destructive"
                          onClick={() => setDeleting(source)}
                        >
                          {t("delete")}
                        </Button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        );
      })}
      {editing && (
        <CapabilitySourceDialog
          key={`${editing.purpose}:${editing.server?.id ?? "new"}`}
          purpose={editing.purpose}
          server={editing.server}
          onClose={() => setEditing(null)}
          onSaved={(inactive) => {
            setEditing(null);
            setNotice(inactive ? t("tools_saved_inactive") : "");
          }}
        />
      )}
      <ConfirmDialogControlled
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        title={t("delete_mcp_server")}
        description={t("confirm_delete_mcp_server", { name: deleting?.name ?? "" })}
        confirmLabel={remove.isPending ? t("deleting") : t("delete")}
        pending={remove.isPending}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting);
        }}
      />
    </div>
  );
}
