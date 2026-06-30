"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import {
  ConfirmedPasswordField,
  isConfirmedPasswordValid
} from "@/components/composites/confirmed-password-field";
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

type McpServerPayload = {
  name: string;
  http_url: string;
  http_auth_type: McpAuthType;
  description: string | null;
  http_auth_config_schema?: { token: string } | null;
};

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
  const [bearerTokenConfirmation, setBearerTokenConfirmation] = useState("");
  const bearerTokenTouched = bearerToken.length > 0 || bearerTokenConfirmation.length > 0;
  const bearerTokenRequired = authType === "bearer" && (!editing || bearerTokenTouched);
  const bearerTokenConfirmed = isConfirmedPasswordValid({
    value: bearerToken,
    confirmation: bearerTokenConfirmation,
    required: bearerTokenRequired
  });
  const bearerTokenValid =
    authType !== "bearer" ||
    (bearerTokenRequired
      ? bearerToken.trim().length > 0 && bearerTokenConfirmed
      : bearerTokenConfirmed);

  function clearBearerToken() {
    setBearerToken("");
    setBearerTokenConfirmation("");
  }

  const save = useMutation({
    mutationFn: async (): Promise<void> => {
      const body: McpServerPayload = {
        name: name.trim(),
        http_url: httpUrl.trim(),
        http_auth_type: authType,
        description: description.trim() || null
      };
      if (authType === "none") body.http_auth_config_schema = null;
      else if (bearerToken) body.http_auth_config_schema = { token: bearerToken };
      else if (!server) body.http_auth_config_schema = null;

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
      clearBearerToken();
      onOpenChange(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const valid = name.trim().length > 0 && httpUrl.trim().length > 0 && bearerTokenValid;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) clearBearerToken();
        onOpenChange(next);
      }}
    >
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
            <Select
              value={authType}
              onValueChange={(value) => {
                setAuthType(value as McpAuthType);
                if (value === "none") {
                  clearBearerToken();
                }
              }}
            >
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
            <ConfirmedPasswordField
              id="mcp-bearer"
              label={t("bearer_token")}
              confirmLabel={t("confirm_bearer_token")}
              value={bearerToken}
              confirmation={bearerTokenConfirmation}
              onValueChange={setBearerToken}
              onConfirmationChange={setBearerTokenConfirmation}
              errorMessage={t("secret_values_do_not_match")}
              description={editing ? t("leave_blank_keep_secret") : undefined}
              autoComplete="off"
              placeholder={editing ? "••••••••" : undefined}
              required={!editing}
            />
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
