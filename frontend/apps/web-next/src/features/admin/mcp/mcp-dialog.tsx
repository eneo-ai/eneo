"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { MCP_KEY, type McpAuthType, type McpServer } from "./mcp";

/** Create or edit a global MCP server (admin catalog, HTTP transport only). */
export function McpServerDialog({
  open,
  onOpenChange,
  server
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Omitted → create mode. */
  server?: McpServer;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const editing = Boolean(server);

  const [name, setName] = useState(server?.name ?? "");
  const [description, setDescription] = useState(server?.description ?? "");
  const [httpUrl, setHttpUrl] = useState(server?.http_url ?? "");
  const [authType, setAuthType] = useState<McpAuthType>(
    (server?.http_auth_type as McpAuthType) ?? "none"
  );
  const [bearerToken, setBearerToken] = useState("");

  const save = useMutation({
    mutationFn: async (): Promise<void> => {
      const body = {
        name: name.trim(),
        http_url: httpUrl.trim(),
        http_auth_type: authType,
        description: description.trim() || null,
        http_auth_config_schema:
          authType === "bearer" && bearerToken ? { token: bearerToken } : null
      };
      if (server) {
        await unwrap(
          browserApi.POST("/api/v1/mcp-servers/{id}/", {
            params: { path: { id: server.id } },
            body
          })
        );
      } else {
        await unwrap(browserApi.POST("/api/v1/mcp-servers/", { body }));
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: MCP_KEY });
      onOpenChange(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const valid = name.trim().length > 0 && httpUrl.trim().length > 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{editing ? t("edit_mcp_server") : t("add_mcp_server")}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="mcp-name">{t("name")}</Label>
            <Input id="mcp-name" value={name} onChange={(event) => setName(event.target.value)} />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="mcp-url">{t("url")}</Label>
            <Input
              id="mcp-url"
              type="url"
              placeholder="https://"
              value={httpUrl}
              onChange={(event) => setHttpUrl(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="mcp-description">{t("description")}</Label>
            <Textarea
              id="mcp-description"
              rows={2}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label>{t("mcp_authentication")}</Label>
            <Select value={authType} onValueChange={(value) => setAuthType(value as McpAuthType)}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">{t("mcp_auth_none")}</SelectItem>
                <SelectItem value="bearer">{t("mcp_auth_bearer")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {authType === "bearer" && (
            <div className="flex flex-col gap-2">
              <Label htmlFor="mcp-bearer">{t("bearer_token")}</Label>
              <Input
                id="mcp-bearer"
                type="password"
                autoComplete="off"
                placeholder={editing ? "••••••••" : undefined}
                value={bearerToken}
                onChange={(event) => setBearerToken(event.target.value)}
              />
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" disabled={save.isPending} onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button disabled={!valid || save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? t("loading") : t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
