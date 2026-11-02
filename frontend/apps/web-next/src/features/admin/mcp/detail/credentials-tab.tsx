"use client";

import { useQueryClient } from "@tanstack/react-query";
import { KeyRound, Lock } from "lucide-react";
import { useTranslations } from "use-intl";
import { useRef, useState } from "react";
import { flushSync } from "react-dom";
import {
  ConfirmedSecretInput,
  confirmedSecretProblem
} from "@/components/composites/confirmed-secret-input";
import {
  FieldProblem,
  fieldProblemProps,
  revealProblems
} from "@/components/composites/field-problem";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAutosave, useDirtySaveStatus } from "@/components/composites/use-autosave";
import { useSetSaveStatus } from "@/components/composites/save-status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { browserApi } from "@/lib/api/browser";
import { useSecretMutation } from "@/lib/api/use-secret-mutation";
import {
  MCP_KEY,
  type McpAuthType,
  type McpServer,
  type McpServerUpdatePayload,
  updateMcpServer
} from "../mcp";
import { credentialPayload } from "../mcp-settings";
import { sendsCredentialOverPlainHttp } from "../credential-transport";

export function CredentialsTab({ server }: { server: McpServer }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const runAuth = useAutosave("mcp-auth");
  const setSaveStatus = useSetSaveStatus();

  const [draftAuth, setDraftAuth] = useState<McpAuthType | null>(null);
  const authType = draftAuth ?? server.http_auth_type ?? "none";
  const managed = server.http_auth_type === "internal" || server.http_auth_type === "bundled";
  const [editing, setEditing] = useState(false);
  const [token, setToken] = useState("");
  const [headerName, setHeaderName] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [submitted, setSubmitted] = useState(false);
  useDirtySaveStatus("mcp-auth", editing && Boolean(token || headerName || draftAuth));
  const editRef = useRef<HTMLButtonElement>(null);
  const tokenRef = useRef<HTMLInputElement>(null);
  const confirmationRef = useRef<HTMLInputElement>(null);
  const headerRef = useRef<HTMLInputElement>(null);
  const transportProblem = sendsCredentialOverPlainHttp(authType, server.http_url)
    ? t("mcp_credential_requires_https")
    : null;
  const headerProblem =
    authType === "api_key_header" &&
    server.http_auth_type !== "api_key_header" &&
    !headerName.trim()
      ? t("required_field")
      : null;

  const invalidate = () => queryClient.invalidateQueries({ queryKey: MCP_KEY });

  function reset() {
    setSaveStatus?.("mcp-auth", null);
    setEditing(false);
    setToken("");
    setConfirmation("");
    setSubmitted(false);
    setHeaderName("");
    setDraftAuth(null);
  }

  // The button pressed disappears, so focus moves to what replaced it: the
  // token's field, and back to the button once the fields go.
  function startEditing() {
    if (saveToken.isPending) return;
    flushSync(() => setEditing(true));
    tokenRef.current?.focus();
  }

  function stopEditing() {
    flushSync(reset);
    editRef.current?.focus();
  }

  function changeAuth(value: string) {
    if (saveToken.isPending) return;
    if (value === "none" && sendsCredentialOverPlainHttp("none", server.http_url)) return;
    reset();
    if (value === "bearer" || value === "api_key_header") {
      setDraftAuth(value);
      flushSync(() => setEditing(true));
      (value === "api_key_header" && server.http_auth_type !== "api_key_header"
        ? headerRef
        : tokenRef
      ).current?.focus();
      return;
    }
    if (value !== "none") return;
    saveToken.mutate({
      http_auth_type: "none",
      http_auth_config_schema: null
    });
  }

  // The body holds the token.
  const saveToken = useSecretMutation({
    mutationFn: (body: McpServerUpdatePayload) =>
      runAuth(async () => {
        const result = await updateMcpServer(browserApi, server.id, body);
        await invalidate();
        stopEditing();
        return result;
      })
  });

  const tokenProblem = confirmedSecretProblem({ value: token, confirmation, isRequired: true });
  // Only spaces is no token either.
  const tokenBlank = token !== "" && token.trim() === "";

  // Problems show at their fields on save, and focus moves to the first.
  function save() {
    if (saveToken.isPending) return;
    const firstProblem = headerProblem
      ? headerRef
      : tokenProblem === "required" || tokenBlank
        ? tokenRef
        : tokenProblem === "mismatch"
          ? confirmationRef
          : null;
    if (firstProblem) {
      revealProblems(() => setSubmitted(true), firstProblem.current);
      return;
    }
    if (transportProblem) {
      setSubmitted(true);
      return;
    }
    saveToken.mutate({
      http_auth_type: authType === "api_key_header" ? "api_key_header" : "bearer",
      http_auth_config_schema: credentialPayload({
        auth: authType === "api_key_header" ? "api_key_header" : "bearer",
        token,
        headerName
      })
    });
  }

  return (
    <SettingsGroup
      id="mcp-auth"
      title={t("mcp_authentication")}
      description={t("mcp_credentials_hint")}
    >
      {managed ? (
        <p className="text-muted-foreground text-sm">
          {t(server.http_auth_type === "bundled" ? "mcp_auth_bundled" : "mcp_auth_internal")}
        </p>
      ) : (
        <SettingsRow title={t("mcp_authentication")} htmlFor="mcp-auth-select">
          <Select value={authType} onValueChange={changeAuth}>
            <SelectTrigger
              id="mcp-auth-select"
              className="w-full sm:w-80"
              aria-busy={saveToken.isPending || undefined}
              {...fieldProblemProps("mcp-auth-select", transportProblem)}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">{t("mcp_auth_none")}</SelectItem>
              <SelectItem value="bearer">{t("mcp_auth_bearer")}</SelectItem>
              <SelectItem value="api_key_header">{t("api_key_header_auth")}</SelectItem>
            </SelectContent>
          </Select>
          <FieldProblem id="mcp-auth-select" problem={transportProblem} />
        </SettingsRow>
      )}

      {!managed && authType !== "none" && (
        <SettingsRow
          title={t(authType === "api_key_header" ? "mcp_api_key_token" : "bearer_token")}
        >
          <div className="flex flex-wrap items-center gap-3">
            {server.has_credentials ? (
              <>
                <Badge className="border-success/30 bg-ax-success-muted text-ax-success gap-1 font-normal">
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
              {authType === "api_key_header" && (
                <div className="flex flex-col gap-2">
                  <Label htmlFor="mcp-edit-header">{t("api_key_header_name")}</Label>
                  <Input
                    ref={headerRef}
                    id="mcp-edit-header"
                    value={headerName}
                    onChange={(event) => setHeaderName(event.target.value)}
                    {...fieldProblemProps(
                      "mcp-edit-header",
                      submitted ? headerProblem : null,
                      "mcp-edit-header-hint"
                    )}
                  />
                  <p id="mcp-edit-header-hint" className="text-muted-foreground text-sm">
                    {t("api_key_header_name_keep_hint")}
                  </p>
                  <FieldProblem id="mcp-edit-header" problem={submitted ? headerProblem : null} />
                </div>
              )}
              <ConfirmedSecretInput
                label={t(authType === "api_key_header" ? "mcp_api_key_token" : "bearer_token")}
                confirmLabel={t(
                  authType === "api_key_header" ? "confirm_api_key" : "confirm_bearer_token"
                )}
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
