"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMediaMatch } from "@/lib/hooks/use-media-match";
import { useRouter } from "@/lib/navigation";
import { useTranslations } from "use-intl";
import { useRef, useState } from "react";
import {
  ConfirmedSecretInput,
  confirmedSecretProblem
} from "@/components/composites/confirmed-secret-input";
import {
  FieldProblem,
  fieldProblemProps,
  revealProblems
} from "@/components/composites/field-problem";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
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
import {
  highestFirst,
  securityClassificationsQueryOptions
} from "@/features/admin/security-classifications/security-classifications";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import { createMcpServer, MCP_KEY, type McpAuthType, type McpServerCreatePayload } from "./mcp";
import { initials } from "./mcp-helpers";
import { TagInput } from "./tag-input";
import { sendsCredentialOverPlainHttp } from "./credential-transport";
import {
  catalogDraft,
  catalogPayload,
  catalogProblems,
  CATALOG_LIMITS,
  credentialPayload
} from "./mcp-settings";

const NO_CLASSIFICATION = "__none__";

/**
 * Quick-add for a global MCP server (admin catalog, HTTP transport only).
 * Problems show at their fields when it is added, and focus moves to the first.
 */
export function McpServerDialog({
  open,
  onOpenChange
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const router = useRouter();
  const queryClient = useQueryClient();
  const pendingBody = useRef<McpServerCreatePayload | null>(null);

  // Owned here, not by the form: a pending add outlives a close and reopen.
  const save = useMutation({
    mutationFn: () => createMcpServer(browserApi, pendingBody.current!),
    onSettled: () => {
      pendingBody.current = null;
    },
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: MCP_KEY });
      toast.success(
        t("mcp_created_with_tools", { count: result.connection.tools_discovered ?? 0 })
      );
      onOpenChange(false);
      router.push(`/admin/mcp-servers/${result.server.id}`);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="overflow-y-auto">
        {/* DialogContent remounts on every opening, so each add starts empty. */}
        <McpServerForm
          pending={save.isPending}
          onSave={(body) => {
            pendingBody.current = body;
            save.mutate();
          }}
          onOpenChange={onOpenChange}
        />
      </DialogContent>
    </Dialog>
  );
}

function McpServerForm({
  pending,
  onSave,
  onOpenChange
}: {
  pending: boolean;
  onSave: (body: McpServerCreatePayload) => void;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  // A touch screen has no Shift, Ctrl or Enter key to point at.
  const coarse = useMediaMatch("(pointer: coarse)");

  const { data: security } = useQuery(securityClassificationsQueryOptions(browserApi));
  const securityEnabled = security?.security_enabled ?? false;
  const classifications = highestFirst(security?.security_classifications ?? []);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [httpUrl, setHttpUrl] = useState("");
  const [authType, setAuthType] = useState<McpAuthType>("none");
  const [bearerToken, setBearerToken] = useState("");
  const [bearerTokenConfirmation, setBearerTokenConfirmation] = useState("");
  const [headerName, setHeaderName] = useState("");
  const [forwardIdentity, setForwardIdentity] = useState(false);
  const [catalog, setCatalog] = useState(catalogDraft);
  const [tags, setTags] = useState<string[]>([]);
  const [iconUrl, setIconUrl] = useState("");
  const [documentationUrl, setDocumentationUrl] = useState("");
  const [classificationId, setClassificationId] = useState<string>(NO_CLASSIFICATION);
  const [submitted, setSubmitted] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);
  const urlRef = useRef<HTMLInputElement>(null);
  const tokenRef = useRef<HTMLInputElement>(null);
  const tokenConfirmationRef = useRef<HTMLInputElement>(null);
  const headerRef = useRef<HTMLInputElement>(null);

  const nameProblem = name.trim() ? null : t("required_field");
  const urlProblem = !httpUrl.trim()
    ? t("required_field")
    : sendsCredentialOverPlainHttp(authType, httpUrl)
      ? t("mcp_credential_requires_https")
      : null;
  const tokenProblem =
    authType !== "none"
      ? confirmedSecretProblem({
          value: bearerToken,
          confirmation: bearerTokenConfirmation,
          isRequired: true
        })
      : null;
  // Only spaces is no token either.
  const tokenBlank = authType !== "none" && bearerToken !== "" && bearerToken.trim() === "";
  const headerProblem =
    authType === "api_key_header" && !headerName.trim() ? t("required_field") : null;
  const limitProblems = catalogProblems(catalog);
  const shown = (problem: string | null) => (submitted ? problem : null);

  function payload(): McpServerCreatePayload {
    const body: McpServerCreatePayload = {
      name: name.trim(),
      http_url: httpUrl.trim(),
      http_auth_type: authType,
      description: description.trim() || null,
      tags: tags.length > 0 ? tags : null,
      icon_url: iconUrl.trim() || null,
      documentation_url: documentationUrl.trim() || null,
      forward_identity: forwardIdentity,
      ...catalogPayload(catalog)
    };
    const credentials = credentialPayload({ auth: authType, token: bearerToken, headerName });
    if (credentials) body.http_auth_config_schema = credentials;
    if (securityEnabled && classificationId !== NO_CLASSIFICATION) {
      body.security_classification = { id: classificationId };
    }
    return body;
  }

  function add() {
    const firstProblem = nameProblem
      ? nameRef
      : urlProblem
        ? urlRef
        : headerProblem
          ? headerRef
          : tokenProblem === "required" || tokenBlank
            ? tokenRef
            : tokenProblem === "mismatch"
              ? tokenConfirmationRef
              : null;
    if (firstProblem) {
      revealProblems(() => setSubmitted(true), firstProblem.current);
      return;
    }
    const firstLimitProblem = limitProblems[0];
    if (firstLimitProblem) {
      revealProblems(() => setSubmitted(true), `mcp-${firstLimitProblem.field}`);
      return;
    }
    onSave(payload());
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>{t("add_mcp_server")}</DialogTitle>
        <DialogDescription>{t("mcp_add_validates_hint")}</DialogDescription>
      </DialogHeader>

      <div className="flex flex-col gap-5">
        <fieldset className="flex flex-col gap-4">
          <legend className="text-muted-foreground mb-1 text-xs font-medium tracking-wider uppercase">
            {t("mcp_section_connection")}
          </legend>
          <div className="flex flex-col gap-2">
            <Label htmlFor="mcp-name">{t("name")}</Label>
            <Input
              ref={nameRef}
              id="mcp-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              {...fieldProblemProps("mcp-name", shown(nameProblem))}
            />
            <FieldProblem id="mcp-name" problem={shown(nameProblem)} />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="mcp-url">{t("url")}</Label>
            <Input
              ref={urlRef}
              id="mcp-url"
              type="url"
              placeholder="https://"
              value={httpUrl}
              onChange={(event) => setHttpUrl(event.target.value)}
              {...fieldProblemProps("mcp-url", shown(urlProblem))}
            />
            <FieldProblem id="mcp-url" problem={shown(urlProblem)} />
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
            <Label htmlFor="mcp-auth-type">{t("mcp_authentication")}</Label>
            <Select
              value={authType}
              onValueChange={(value) => {
                setAuthType(value as McpAuthType);
                if (value === "none") {
                  setBearerToken("");
                  setBearerTokenConfirmation("");
                }
              }}
            >
              <SelectTrigger id="mcp-auth-type" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">{t("mcp_auth_none")}</SelectItem>
                <SelectItem value="bearer">{t("mcp_auth_bearer")}</SelectItem>
                <SelectItem value="api_key_header">{t("api_key_header_auth")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {authType === "api_key_header" && (
            <div className="flex flex-col gap-2">
              <Label htmlFor="mcp-header">{t("api_key_header_name")}</Label>
              <Input
                id="mcp-header"
                ref={headerRef}
                value={headerName}
                onChange={(event) => setHeaderName(event.target.value)}
                {...fieldProblemProps("mcp-header", shown(headerProblem))}
              />
              <FieldProblem id="mcp-header" problem={shown(headerProblem)} />
            </div>
          )}
          {authType !== "none" && (
            <ConfirmedSecretInput
              label={t(authType === "bearer" ? "bearer_token" : "mcp_api_key_token")}
              confirmLabel={t(authType === "bearer" ? "confirm_bearer_token" : "confirm_api_key")}
              value={bearerToken}
              confirmation={bearerTokenConfirmation}
              onValueChange={setBearerToken}
              onConfirmationChange={setBearerTokenConfirmation}
              mismatchMessage={t("secret_values_do_not_match")}
              autoComplete="off"
              isRequired
              requiredMessage={t("required_field")}
              valueError={submitted && tokenBlank ? t("required_field") : undefined}
              showErrors={submitted}
              valueRef={tokenRef}
              confirmationRef={tokenConfirmationRef}
            />
          )}
          <div className="flex flex-col gap-2">
            <Label htmlFor="mcp-forward-identity" className="flex min-h-11 items-center gap-2">
              <input
                id="mcp-forward-identity"
                type="checkbox"
                checked={forwardIdentity}
                onChange={(event) => setForwardIdentity(event.target.checked)}
                aria-describedby="mcp-forward-identity-hint"
              />
              {t("mcp_forward_identity")}
            </Label>
            <p id="mcp-forward-identity-hint" className="text-muted-foreground text-sm">
              {t("mcp_forward_identity_hint")}
            </p>
          </div>
          <details>
            <summary className="cursor-pointer text-sm font-medium">
              {t("mcp_catalog_safety")}
            </summary>
            <p className="text-muted-foreground mt-2 text-sm">{t("mcp_catalog_safety_hint")}</p>
            <div className="mt-3 flex flex-col gap-3">
              {CATALOG_LIMITS.map(({ field, label, hint, max }) => {
                const problem = limitProblems.find((problem) => problem.field === field);
                const message = problem
                  ? t("form_problem_whole_number_between", { min: 1, max })
                  : null;
                return (
                  <div key={field} className="flex flex-col gap-2">
                    <Label htmlFor={`mcp-${field}`}>{t(label)}</Label>
                    <Input
                      id={`mcp-${field}`}
                      type="number"
                      min={1}
                      max={max}
                      step={1}
                      value={catalog[field]}
                      onChange={(event) =>
                        setCatalog({ ...catalog, [field]: Number(event.target.value) })
                      }
                      {...fieldProblemProps(`mcp-${field}`, shown(message))}
                    />
                    <p className="text-muted-foreground text-sm">{t(hint)}</p>
                    <FieldProblem id={`mcp-${field}`} problem={shown(message)} />
                  </div>
                );
              })}
            </div>
          </details>
        </fieldset>

        <fieldset className="flex flex-col gap-4">
          <legend className="text-muted-foreground mb-1 text-xs font-medium tracking-wider uppercase">
            {t("mcp_section_presentation")}
          </legend>
          <div className="flex flex-col gap-2">
            <Label htmlFor="mcp-tags">{t("mcp_tags")}</Label>
            <TagInput
              id="mcp-tags"
              value={tags}
              onChange={setTags}
              placeholder={t(coarse ? "mcp_tags_placeholder_touch" : "mcp_tags_placeholder")}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="mcp-icon">{t("mcp_icon_url")}</Label>
            <div className="flex items-center gap-3">
              <Avatar className="size-9 rounded-md">
                {iconUrl.trim() ? <AvatarImage src={iconUrl.trim()} alt="" /> : null}
                <AvatarFallback className="rounded-md text-xs font-medium">
                  {initials(name || "?")}
                </AvatarFallback>
              </Avatar>
              <Input
                id="mcp-icon"
                type="url"
                placeholder="https://"
                value={iconUrl}
                onChange={(event) => setIconUrl(event.target.value)}
              />
            </div>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="mcp-docs">{t("mcp_documentation_url")}</Label>
            <Input
              id="mcp-docs"
              type="url"
              placeholder="https://"
              value={documentationUrl}
              onChange={(event) => setDocumentationUrl(event.target.value)}
            />
          </div>
          {securityEnabled && (
            <div className="flex flex-col gap-2">
              <Label htmlFor="mcp-classification">{t("security_classification")}</Label>
              <Select value={classificationId} onValueChange={setClassificationId}>
                <SelectTrigger id="mcp-classification" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NO_CLASSIFICATION}>{t("none")}</SelectItem>
                  {classifications.map((classification) => (
                    <SelectItem key={classification.id} value={classification.id}>
                      {classification.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </fieldset>
      </div>

      <DialogFooter>
        <Button variant="outline" disabled={pending} onClick={() => onOpenChange(false)}>
          {t("cancel")}
        </Button>
        {/* Never disabled: busy, it keeps focus and a second press is ignored. */}
        <Button aria-busy={pending || undefined} onClick={add}>
          {pending ? t("mcp_connecting") : t("add_mcp_server")}
        </Button>
      </DialogFooter>
    </>
  );
}
