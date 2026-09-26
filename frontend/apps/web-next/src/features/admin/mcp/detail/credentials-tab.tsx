"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Lock } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { flushSync } from "react-dom";
import {
  ConfirmedSecretInput,
  confirmedSecretProblem
} from "@/components/composites/confirmed-secret-input";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAutosave } from "@/components/composites/use-autosave";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import { MCP_KEY, type McpAuthType, type McpServer, updateMcpServer } from "../mcp";

export function CredentialsTab({ server }: { server: McpServer }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const runAuth = useAutosave("mcp-auth");

  const authType = (server.http_auth_type as McpAuthType) ?? "none";
  const [editing, setEditing] = useState(false);
  const [token, setToken] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const editRef = useRef<HTMLButtonElement>(null);
  const tokenRef = useRef<HTMLInputElement>(null);
  const confirmationRef = useRef<HTMLInputElement>(null);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: MCP_KEY });

  function reset() {
    setEditing(false);
    setToken("");
    setConfirmation("");
    setSubmitted(false);
  }

  // The button pressed disappears, so focus moves to what replaced it: the
  // token's field, and back to the button once the fields go.
  function startEditing() {
    flushSync(() => setEditing(true));
    tokenRef.current?.focus();
  }

  function stopEditing() {
    flushSync(reset);
    editRef.current?.focus();
  }

  function changeAuth(value: string) {
    reset();
    void runAuth(async () => {
      await updateMcpServer(
        browserApi,
        server.id,
        value === "none"
          ? { http_auth_type: "none", http_auth_config_schema: null }
          : { http_auth_type: "bearer" }
      );
      await invalidate();
    });
  }

  const saveToken = useMutation({
    mutationFn: () =>
      updateMcpServer(browserApi, server.id, {
        http_auth_type: "bearer",
        http_auth_config_schema: { token }
      }),
    onSuccess: () => {
      void invalidate();
      stopEditing();
    },
    onError: (error) => toastApiError(error, t)
  });

  const tokenProblem = confirmedSecretProblem({ value: token, confirmation, isRequired: true });
  // Only spaces is no token either.
  const tokenBlank = token !== "" && token.trim() === "";

  // Problems show at their fields on save, and focus moves to the first.
  function save() {
    if (saveToken.isPending) return;
    const firstProblem =
      tokenProblem === "required" || tokenBlank
        ? tokenRef
        : tokenProblem === "mismatch"
          ? confirmationRef
          : null;
    if (firstProblem) {
      // Rendered before focus moves, so the field is read with its error.
      flushSync(() => setSubmitted(true));
      firstProblem.current?.focus();
      return;
    }
    saveToken.mutate();
  }

  return (
    <SettingsGroup
      id="mcp-auth"
      title={t("mcp_authentication")}
      description={t("mcp_credentials_hint")}
    >
      <SettingsRow title={t("mcp_authentication")} htmlFor="mcp-auth-select">
        <Select value={authType} onValueChange={changeAuth}>
          <SelectTrigger id="mcp-auth-select" className="w-full sm:w-80">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">{t("mcp_auth_none")}</SelectItem>
            <SelectItem value="bearer">{t("mcp_auth_bearer")}</SelectItem>
          </SelectContent>
        </Select>
      </SettingsRow>

      {authType === "bearer" && (
        <SettingsRow title={t("bearer_token")}>
          <div className="flex flex-wrap items-center gap-3">
            {server.has_credentials ? (
              <>
                <Badge className="border-success/30 bg-success/15 text-success gap-1 font-normal">
                  <KeyRound className="size-3" aria-hidden="true" />
                  {t("mcp_token_configured")}
                </Badge>
                {server.credential_preview && (
                  <code className="text-muted-foreground font-mono text-sm">
                    {server.credential_preview}
                  </code>
                )}
              </>
            ) : (
              <Badge variant="outline" className="text-muted-foreground gap-1 font-normal">
                <Lock className="size-3" aria-hidden="true" />
                {t("mcp_no_token")}
              </Badge>
            )}
            {!editing && (
              <Button ref={editRef} variant="outline" size="sm" onClick={startEditing}>
                {server.has_credentials ? t("mcp_replace_token") : t("mcp_add_token")}
              </Button>
            )}
          </div>

          {editing && (
            <div className="mt-3 flex flex-col gap-3">
              <ConfirmedSecretInput
                label={t("bearer_token")}
                confirmLabel={t("confirm_bearer_token")}
                value={token}
                confirmation={confirmation}
                onValueChange={setToken}
                onConfirmationChange={setConfirmation}
                mismatchMessage={t("secret_values_do_not_match")}
                autoComplete="off"
                isRequired
                requiredMessage={t("required_field")}
                valueError={submitted && tokenBlank ? t("required_field") : undefined}
                showErrors={submitted}
                valueRef={tokenRef}
                confirmationRef={confirmationRef}
              />
              <div className="flex items-center gap-2">
                {/* Never disabled: busy, it keeps focus and a second press is ignored. */}
                <Button aria-busy={saveToken.isPending || undefined} onClick={save}>
                  {saveToken.isPending ? t("loading") : t("save")}
                </Button>
                <Button variant="ghost" disabled={saveToken.isPending} onClick={stopEditing}>
                  {t("cancel")}
                </Button>
              </div>
            </div>
          )}
        </SettingsRow>
      )}
    </SettingsGroup>
  );
}
