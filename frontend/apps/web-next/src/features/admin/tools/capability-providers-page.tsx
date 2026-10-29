"use client";

import { invalidateSpaces } from "@/features/spaces/space";

import { DropdownMenu } from "@astryxdesign/core/DropdownMenu";
import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { CheckCircle2, CircleDashed, Plus, ShieldCheck, TriangleAlert } from "lucide-react";
import Link from "@/lib/link";
import { useTranslations } from "use-intl";
import { useState } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { PageHeader } from "@/components/composites/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  CAPABILITIES,
  readinessKey,
  type Capability,
  type CapabilityDescriptor
} from "@/features/capabilities/capabilities";
import { browserApi } from "@/lib/api/browser";
import { getErrorMessage } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/utils";
import {
  BUNDLED_KEY,
  bundledToolsQueryOptions,
  createBundledMcpServer,
  deleteMcpServer,
  MCP_KEY,
  mcpServersQueryOptions,
  setCapabilityProviderActive,
  type McpServer
} from "../mcp/mcp";
import { bundledIdentity, SOURCE_KINDS, sourceKindOf, type BundledTool } from "./bundled";
import { CapabilitySourceDialog } from "./capability-source-dialog";
import { RuntimeStatusCard } from "./runtime-status";
import { TOOLS_TAB_HREF } from "./tools-tabs";

const DEPLOYMENT_GUIDE_URL =
  "https://docs.eneo.ai/docs/builtin-tool-servers#bundled-isolated-providers";

/** The state of a source: blocked, active or inactive. */
function StatusBadge({ source }: { source: McpServer }) {
  const t = useTranslations();
  const active = source.is_enabled === true;
  const blocked = Boolean(source.readiness_reason);
  return (
    <Badge variant={blocked ? "destructive" : active ? "secondary" : "outline"}>
      {blocked ? (
        <TriangleAlert className="size-3" />
      ) : active ? (
        <CheckCircle2 className="size-3" />
      ) : (
        <CircleDashed className="size-3" />
      )}
      {t(blocked ? "tools_blocked" : active ? "tools_active" : "tools_inactive")}
    </Badge>
  );
}

/**
 * The provider built into Eneo, offered as a function's first source ahead
 * of the external form: one button turns it on as the tenant default. A
 * deployment without the tool runtime shows why it cannot be turned on.
 */
function BundledOffer({
  capability,
  bundled,
  busy,
  onTurnOn,
  onConnectExternal
}: {
  capability: CapabilityDescriptor;
  bundled: BundledTool;
  busy: boolean;
  onTurnOn: () => void;
  onConnectExternal: () => void;
}) {
  const t = useTranslations();
  return (
    <div className="flex flex-col gap-3 p-5">
      <div className="bg-ax-muted rounded-ax-element flex flex-wrap items-center gap-4 p-4">
        <span
          aria-hidden="true"
          className={cn(
            "rounded-ax-element flex size-10 shrink-0 items-center justify-center",
            bundled.available
              ? "bg-ax-accent-muted text-ax-text-accent"
              : "bg-ax-surface text-ax-text-secondary"
          )}
        >
          <ShieldCheck className="size-5" />
        </span>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold">{t("mcp_auth_bundled")}</span>
            <Badge variant={bundled.available ? "secondary" : "outline"}>
              {t(bundled.available ? "tools_builtin_recommended" : "tools_builtin_unavailable")}
            </Badge>
          </div>
          <p className="text-ax-text-secondary max-w-[62ch] text-sm">
            {bundled.available ? (
              t(capability.bundledDescription ?? "tools_builtin_menu_description")
            ) : (
              <>
                {t("tools_builtin_unavailable_hint")}{" "}
                <a
                  href={DEPLOYMENT_GUIDE_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-ax-text font-medium underline underline-offset-2"
                >
                  {t("tools_builtin_deployment_guide")}
                </a>
              </>
            )}
          </p>
        </div>
        {/* Busy, it stays enabled so it keeps focus; a second press is ignored. */}
        <Button disabled={!bundled.available} aria-busy={busy || undefined} onClick={onTurnOn}>
          {t("tools_builtin_turn_on")}
        </Button>
      </div>
      <p className="text-ax-text-secondary text-sm">
        {t("tools_prefer_own_service")}{" "}
        <button
          type="button"
          onClick={onConnectExternal}
          className="text-ax-text focus-visible:outline-ring rounded-ax-inner font-medium underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          {t("tools_connect_external")}
        </button>
      </p>
    </div>
  );
}

/** One line under a source's name: the model, what the bundled provider does, or the address. */
function SourceDetail({
  source,
  capability
}: {
  source: McpServer;
  capability: CapabilityDescriptor;
}) {
  const t = useTranslations();
  const kind = sourceKindOf(source.http_auth_type);
  if (kind === "internal") {
    return (
      <p className="text-ax-text-secondary text-sm break-all">
        {t("tools_source_model")} ·{" "}
        {source.image_model?.nickname ||
          source.image_model?.name ||
          t("tools_readiness_model_missing")}
        {source.image_model?.provider_name ? ` · ${source.image_model.provider_name}` : ""}
      </p>
    );
  }
  if (kind === "bundled") {
    // The runtime address is deployment plumbing; say what the provider does, in one line.
    return capability.bundledSummary ? (
      <p className="text-ax-text-secondary text-sm">{t(capability.bundledSummary)}</p>
    ) : null;
  }
  return (
    <p className="text-ax-text-secondary text-sm break-all">
      {t("tools_source_external")} · {source.http_url}
    </p>
  );
}

/**
 * The functions and their sources. `embedded` leaves the page header to the
 * surrounding tools page (tools-page.tsx), which holds the tabs.
 */
export function CapabilityProvidersPage({ embedded = false }: { embedded?: boolean } = {}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const { data: servers } = useSuspenseQuery(mcpServersQueryOptions(browserApi));
  const bundledTools = useQuery(bundledToolsQueryOptions(browserApi));
  const [editing, setEditing] = useState<{ purpose: Capability; server: McpServer | null } | null>(
    null
  );
  const [deleting, setDeleting] = useState<McpServer | null>(null);
  const [notice, setNotice] = useState<{ purpose: Capability | null; text: string } | null>(null);
  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: MCP_KEY }),
      queryClient.invalidateQueries({ queryKey: BUNDLED_KEY }),
      invalidateSpaces(queryClient)
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
  // Adds the provider built into Eneo: activated as the tenant default when
  // `activate` is set, which is the case unless another source is the default.
  const addBundled = useMutation({
    mutationFn: ({
      tool,
      activate
    }: {
      tool: string;
      activate: boolean;
      capability: CapabilityDescriptor;
    }) => createBundledMcpServer(browserApi, tool, activate),
    onSuccess: (_, { activate, capability }) => {
      setNotice({
        purpose: capability.purpose,
        text: activate
          ? t("tools_builtin_turned_on", {
              capability: t(capability.purpose).toLocaleLowerCase()
            })
          : t("tools_saved_inactive")
      });
      void invalidate().catch((cause) => toastApiError(cause, t));
    },
    onError: (cause) =>
      toast.error(
        getErrorMessage(cause, t) || t("tools_bundled_add_failed", { name: t("mcp_auth_bundled") })
      )
  });

  // Servers built into Eneo that this tenant has not added yet. A function
  // card also shows a provider the deployment has not enabled, so admins
  // learn it exists.
  const bundledToAdd = (bundledTools.data?.items ?? []).filter((tool) => !tool.mcp_server_id);
  const bundledProviderFor = (purpose: Capability) =>
    bundledToAdd.find((tool) => tool.purpose === purpose);

  return (
    <div className={cn("flex w-full flex-col gap-6", !embedded && "mx-auto max-w-5xl pb-16")}>
      {!embedded && (
        <PageHeader title={t("tools")} tour="admin-tools">
          <Button asChild variant="outline">
            <Link href={TOOLS_TAB_HREF["mcp-servers"]}>{t("mcp_servers")}</Link>
          </Button>
        </PageHeader>
      )}
      <RuntimeStatusCard status={bundledTools.data?.runtime} />
      <p className="text-muted-foreground max-w-2xl text-sm">{t("tools_functions_description")}</p>
      {notice && notice.purpose === null && (
        <p role="status" className="text-sm">
          {notice.text}
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
        const bundled = bundledProviderFor(capability.purpose);
        const configure = (server: McpServer | null = null) =>
          setEditing({ purpose: capability.purpose, server });
        const turnOn = (activateNow: boolean) => {
          if (!bundled || addBundled.isPending) return;
          addBundled.mutate({ tool: bundled.tool, activate: activateNow, capability });
        };
        const label = t(capability.purpose);
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
                    {label}
                  </h2>
                  {!activeDefault && (
                    <p className="text-muted-foreground mt-1 text-sm">{t("tools_no_default")}</p>
                  )}
                </div>
              </div>
              {bundled && sources.length === 0 ? null : bundled?.available ? (
                // Two kinds of source: the one built into Eneo, or an external server.
                <DropdownMenu
                  button={{
                    label: t("tools_add_source"),
                    variant: "secondary",
                    size: "sm",
                    icon: <Plus className="size-4" />,
                    isDisabled: addBundled.isPending
                  }}
                  placement="below"
                  alignment="end"
                  menuWidth={320}
                  items={[
                    {
                      id: "bundled",
                      label: t("mcp_auth_bundled"),
                      description: t("tools_builtin_menu_description"),
                      icon: <ShieldCheck className="size-4" />,
                      endContent: (
                        <Badge variant="secondary">{t("tools_builtin_recommended")}</Badge>
                      ),
                      onClick: () => turnOn(!activeDefault)
                    },
                    {
                      id: "external",
                      label: t("tools_source_external"),
                      description: t("tools_external_menu_description"),
                      icon: <SOURCE_KINDS.external.icon className="size-4" />,
                      onClick: () => configure()
                    }
                  ]}
                />
              ) : (
                <Button size="sm" onClick={() => configure()}>
                  <Plus className="size-4" />
                  {sources.length
                    ? t("tools_add_source")
                    : t("capability_configure", { capability: label.toLocaleLowerCase() })}
                </Button>
              )}
            </header>
            {notice && notice.purpose === capability.purpose && (
              <p role="status" className="border-b p-5 text-sm">
                {notice.text}
              </p>
            )}
            {bundled && sources.length === 0 && (
              <BundledOffer
                capability={capability}
                bundled={bundled}
                busy={addBundled.isPending}
                onTurnOn={() => turnOn(true)}
                onConnectExternal={() => configure()}
              />
            )}
            {sources.length > 0 && (
              <ul className="divide-y">
                {sources.map((source) => {
                  const active = source.is_enabled === true;
                  const blocked = Boolean(source.readiness_reason);
                  const kind = SOURCE_KINDS[sourceKindOf(source.http_auth_type)];
                  const identity = bundledIdentity(source);
                  return (
                    <li key={source.id} className="space-y-3 p-5">
                      <div className="flex flex-wrap items-start justify-between gap-4">
                        <div className="min-w-0 space-y-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <h3 className="font-medium">
                              {identity ? t(identity.name) : source.name}
                            </h3>
                            {/* Every source carries its kind: Eneo itself, Eneo's tool service, or an external server. */}
                            <Badge variant="outline">
                              <kind.icon className="size-3" aria-hidden="true" />
                              {t(kind.label)}
                            </Badge>
                            {source.audience === "groups" && (
                              <Badge variant="outline">{t("tools_group_override")}</Badge>
                            )}
                          </div>
                          <SourceDetail source={source} capability={capability} />
                          {source.audience === "groups" && (
                            <p className="text-muted-foreground text-xs">
                              {(source.user_groups ?? []).map((group) => group.name).join(", ")}
                            </p>
                          )}
                        </div>
                        <StatusBadge source={source} />
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
                        {/* A bundled server's address and credential come from the
                            deployment: there is nothing to change on it. */}
                        {source.http_auth_type !== "bundled" && (
                          <Button size="sm" variant="outline" onClick={() => configure(source)}>
                            {t("tools_change")}
                          </Button>
                        )}
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
            {capability.guide && sources.length > 0 && (
              // Usage guidance lives here and in the docs, not in assistant settings.
              <p className="text-muted-foreground border-t p-5 text-sm">
                {t(capability.guide.hint)}{" "}
                <a
                  href={capability.guide.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-ax-text font-medium underline underline-offset-2"
                >
                  {t(capability.guide.label)}
                </a>
              </p>
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
            setNotice(inactive ? { purpose: null, text: t("tools_saved_inactive") } : null);
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
