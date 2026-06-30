"use client";

import { useMutation, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import {
  ChevronLeft,
  KeyRound,
  ListChecks,
  MoreHorizontal,
  Settings2,
  Shield,
  Trash2
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { PageHeader } from "@/components/composites/page-header";
import { SaveStatusIndicator, SaveStatusProvider } from "@/components/composites/save-status";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { securityClassificationsQueryOptions } from "@/features/admin/security-classifications/security-classifications";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import { deleteMcpServer, MCP_KEY, mcpServersQueryOptions, setMcpOrgEnabled } from "../mcp";
import { isQuarantined } from "../mcp-helpers";
import { CredentialsTab } from "./credentials-tab";
import { OverviewTab } from "./overview-tab";
import { SecurityTab } from "./security-tab";
import { ToolsTab } from "./tools-tab";

const TABS = ["overview", "tools", "security", "credentials"] as const;
type Tab = (typeof TABS)[number];

function resolveTab(value: string | undefined): Tab {
  return TABS.includes(value as Tab) ? (value as Tab) : "overview";
}

export function McpServerDetail({
  serverId,
  initialTab
}: {
  serverId: string;
  initialTab?: string;
}) {
  const t = useTranslations();
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();

  const { data: servers } = useSuspenseQuery(mcpServersQueryOptions(browserApi));
  const { data: security } = useSuspenseQuery(securityClassificationsQueryOptions(browserApi));
  const server = servers.find((entry) => entry.id === serverId);

  const [tab, setTab] = useState<Tab>(resolveTab(initialTab));
  const [showDelete, setShowDelete] = useState(false);

  // The server can vanish if deleted in another tab; bounce back to the list.
  useEffect(() => {
    if (!server) router.replace("/admin/mcp-servers");
  }, [server, router]);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: MCP_KEY });

  const setEnabled = useMutation({
    mutationFn: (next: boolean) => setMcpOrgEnabled(browserApi, serverId, next),
    onSuccess: invalidate,
    onError: (error) => toastApiError(error, t)
  });

  const remove = useMutation({
    mutationFn: () => deleteMcpServer(browserApi, serverId),
    onSuccess: () => {
      invalidate();
      router.push("/admin/mcp-servers");
    },
    onError: (error) => toastApiError(error, t)
  });

  if (!server) return null;

  const securityEnabled = security.security_enabled;
  const quarantined = isQuarantined(server, securityEnabled);
  const toggleBlocked = quarantined && !server.is_org_enabled;
  // The security tab only exists when classifications are enforced; a deep link
  // to it otherwise falls back to overview so the page never renders blank.
  const activeTab = tab === "security" && !securityEnabled ? "overview" : tab;

  function selectTab(next: string) {
    const value = resolveTab(next);
    setTab(value);
    router.replace(value === "overview" ? pathname : `${pathname}?tab=${value}`, { scroll: false });
  }

  return (
    <SaveStatusProvider>
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
        <div className="flex flex-col gap-1">
          <Link
            href="/admin/mcp-servers"
            className="text-muted-foreground hover:text-foreground flex w-fit items-center gap-1 text-sm"
          >
            <ChevronLeft className="size-4" />
            {t("mcp_servers")}
          </Link>
          <PageHeader title={server.name}>
            <SaveStatusIndicator />
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="inline-flex">
                  <Switch
                    checked={server.is_org_enabled}
                    disabled={setEnabled.isPending || toggleBlocked}
                    aria-label={t("mcp_toggle_server", { name: server.name })}
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
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" aria-label={t("actions")}>
                  <MoreHorizontal className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem variant="destructive" onSelect={() => setShowDelete(true)}>
                  <Trash2 className="size-4" /> {t("delete")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </PageHeader>
        </div>

        <Tabs value={activeTab} onValueChange={selectTab}>
          <TabsList>
            <TabsTrigger value="overview">
              <Settings2 className="size-4" /> {t("mcp_tab_overview")}
            </TabsTrigger>
            <TabsTrigger value="tools">
              <ListChecks className="size-4" /> {t("mcp_server_tools")}
            </TabsTrigger>
            {securityEnabled && (
              <TabsTrigger value="security">
                <Shield className="size-4" /> {t("security_classification")}
              </TabsTrigger>
            )}
            <TabsTrigger value="credentials">
              <KeyRound className="size-4" /> {t("mcp_tab_credentials")}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="overview" className="pt-4">
            <OverviewTab server={server} />
          </TabsContent>
          <TabsContent value="tools" className="pt-4">
            <ToolsTab serverId={server.id} />
          </TabsContent>
          {securityEnabled && (
            <TabsContent value="security" className="pt-4">
              <SecurityTab server={server} />
            </TabsContent>
          )}
          <TabsContent value="credentials" className="pt-4">
            <CredentialsTab server={server} />
          </TabsContent>
        </Tabs>
      </div>

      <ConfirmDialogControlled
        open={showDelete}
        onOpenChange={setShowDelete}
        title={t("delete_mcp_server")}
        description={t("confirm_delete_mcp_server", { name: server.name })}
        confirmLabel={remove.isPending ? t("deleting") : t("delete")}
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </SaveStatusProvider>
  );
}
