"use client";

import { useMutation, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { MoreHorizontal, Pencil, Plus, Trash2, Wrench } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { EmptyState } from "@/components/composites/empty-state";
import { PageHeader } from "@/components/composites/page-header";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { McpServerDialog } from "./mcp-dialog";
import { McpToolsDialog } from "./mcp-tools-dialog";
import { MCP_KEY, mcpServersQueryOptions, type McpServer } from "./mcp";

function McpRow({ server }: { server: McpServer }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [showEdit, setShowEdit] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [showTools, setShowTools] = useState(false);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: MCP_KEY });

  const setEnabled = useMutation({
    mutationFn: (next: boolean) =>
      next
        ? unwrap(
            browserApi.POST("/api/v1/mcp-servers/settings/{mcp_server_id}/", {
              params: { path: { mcp_server_id: server.id } },
              body: {}
            })
          )
        : unwrap(
            browserApi.DELETE("/api/v1/mcp-servers/settings/{mcp_server_id}/", {
              params: { path: { mcp_server_id: server.id } }
            })
          ),
    onSuccess: invalidate,
    onError: (error) => toastApiError(error, t)
  });

  const remove = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.DELETE("/api/v1/mcp-servers/{id}/", { params: { path: { id: server.id } } })
      ),
    onSuccess: () => {
      invalidate();
      setShowDelete(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <TableRow>
      <TableCell>
        <Switch
          checked={server.is_org_enabled}
          disabled={setEnabled.isPending}
          aria-label={server.name}
          onCheckedChange={(checked) => setEnabled.mutate(checked)}
        />
      </TableCell>
      <TableCell className="font-medium">
        {server.name}
        {server.description && (
          <span className="text-muted-foreground line-clamp-1 text-xs">{server.description}</span>
        )}
      </TableCell>
      <TableCell className="text-muted-foreground max-w-xs truncate font-mono text-xs">
        {server.http_url}
      </TableCell>
      <TableCell className="w-12">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label={t("actions")}>
              <MoreHorizontal className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => setShowEdit(true)}>
              <Pencil className="size-4" /> {t("edit")}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => setShowTools(true)}>
              <Wrench className="size-4" /> {t("mcp_server_tools")}
            </DropdownMenuItem>
            <DropdownMenuItem variant="destructive" onSelect={() => setShowDelete(true)}>
              <Trash2 className="size-4" /> {t("delete")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </TableCell>
      <McpServerDialog open={showEdit} onOpenChange={setShowEdit} server={server} />
      <McpToolsDialog
        serverId={server.id}
        serverName={server.name}
        open={showTools}
        onOpenChange={setShowTools}
      />
      <ConfirmDialogControlled
        open={showDelete}
        onOpenChange={setShowDelete}
        title={t("delete_mcp_server")}
        description={t("confirm_delete_mcp_server", { name: server.name })}
        confirmLabel={remove.isPending ? t("deleting") : t("delete")}
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </TableRow>
  );
}

export function McpServersPage() {
  const t = useTranslations();
  const { data: servers } = useSuspenseQuery(mcpServersQueryOptions(browserApi));
  const [showAdd, setShowAdd] = useState(false);

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
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-16">{t("status")}</TableHead>
              <TableHead>{t("name")}</TableHead>
              <TableHead>{t("url")}</TableHead>
              <TableHead className="w-12" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {servers.map((server) => (
              <McpRow key={server.id} server={server} />
            ))}
          </TableBody>
        </Table>
      )}

      <McpServerDialog open={showAdd} onOpenChange={setShowAdd} />
    </div>
  );
}
