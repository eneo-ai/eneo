"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { flushSync } from "react-dom";
import {
  ConfirmedSecretInput,
  confirmedSecretProblem
} from "@/components/composites/confirmed-secret-input";
import { FieldProblem, fieldProblemProps } from "@/components/composites/field-problem";
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

  const { data: security } = useQuery(securityClassificationsQueryOptions(browserApi));
  const securityEnabled = security?.security_enabled ?? false;
  const classifications = highestFirst(security?.security_classifications ?? []);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [httpUrl, setHttpUrl] = useState("");
  const [authType, setAuthType] = useState<McpAuthType>("none");
  const [bearerToken, setBearerToken] = useState("");
  const [bearerTokenConfirmation, setBearerTokenConfirmation] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [iconUrl, setIconUrl] = useState("");
  const [documentationUrl, setDocumentationUrl] = useState("");
  const [classificationId, setClassificationId] = useState<string>(NO_CLASSIFICATION);
  const [submitted, setSubmitted] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);
  const urlRef = useRef<HTMLInputElement>(null);
  const tokenRef = useRef<HTMLInputElement>(null);
  const tokenConfirmationRef = useRef<HTMLInputElement>(null);

  function reset() {
    setName("");
    setDescription("");
    setHttpUrl("");
    setAuthType("none");
    setBearerToken("");
    setBearerTokenConfirmation("");
    setTags([]);
    setIconUrl("");
    setDocumentationUrl("");
    setClassificationId(NO_CLASSIFICATION);
    setSubmitted(false);
  }

  const nameProblem = name.trim() ? null : t("required_field");
  const urlProblem = httpUrl.trim() ? null : t("required_field");
  const tokenProblem =
    authType === "bearer"
      ? confirmedSecretProblem({
          value: bearerToken,
          confirmation: bearerTokenConfirmation,
          isRequired: true
        })
      : null;
  // Only spaces is no token either.
  const tokenBlank = authType === "bearer" && bearerToken !== "" && bearerToken.trim() === "";
  const shown = (problem: string | null) => (submitted ? problem : null);

  const save = useMutation({
    mutationFn: async () => {
      const body: McpServerCreatePayload = {
        name: name.trim(),
        http_url: httpUrl.trim(),
        http_auth_type: authType,
        description: description.trim() || null,
        tags: tags.length > 0 ? tags : null,
        icon_url: iconUrl.trim() || null,
        documentation_url: documentationUrl.trim() || null
      };
      if (authType === "bearer" && bearerToken) {
        body.http_auth_config_schema = { token: bearerToken };
      }
      if (securityEnabled && classificationId !== NO_CLASSIFICATION) {
        body.security_classification = { id: classificationId };
      }
      return createMcpServer(browserApi, body);
    },
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: MCP_KEY });
      toast.success(
        t("mcp_created_with_tools", { count: result.connection.tools_discovered ?? 0 })
      );
      onOpenChange(false);
      reset();
      router.push(`/admin/mcp-servers/${result.server.id}`);
    },
    onError: (error) => toastApiError(error, t)
  });

  function add() {
    if (save.isPending) return;
    const firstProblem = nameProblem
      ? nameRef
      : urlProblem
        ? urlRef
        : tokenProblem === "required" || tokenBlank
          ? tokenRef
          : tokenProblem === "mismatch"
            ? tokenConfirmationRef
            : null;
    if (firstProblem) {
      // Rendered before focus moves, so the field is read with its error.
      flushSync(() => setSubmitted(true));
      firstProblem.current?.focus();
      return;
    }
    save.mutate();
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent className="max-h-[90vh] overflow-y-auto">
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
                </SelectContent>
              </Select>
            </div>
            {authType === "bearer" && (
              <ConfirmedSecretInput
                label={t("bearer_token")}
                confirmLabel={t("confirm_bearer_token")}
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
                placeholder={t("mcp_tags_placeholder")}
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
          <Button variant="outline" disabled={save.isPending} onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          {/* Never disabled: busy, it keeps focus and a second press is ignored. */}
          <Button aria-busy={save.isPending || undefined} onClick={add}>
            {save.isPending ? t("mcp_connecting") : t("add_mcp_server")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
