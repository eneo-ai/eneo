"use client";

import { useMutation, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { ChevronRight, Plus, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";
import { ConfirmDialog } from "@/components/composites/confirm-dialog";
import { PageHeader } from "@/components/composites/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import {
  type HelperKind,
  type HelperTemplate,
  type RoleAssignment,
  ROLES_KEY,
  TEMPLATES_KEY,
  helpRolesQueryOptions,
  helpTemplatesQueryOptions
} from "@/features/admin/help-assistants/help-assistants";

function roleKindLabel(kind: HelperKind, t: (key: string) => string): string {
  switch (kind) {
    case "prompt_guide":
      return t("admin_help_assistants_role_kind_prompt_guide");
    default:
      return kind;
  }
}

function useInvalidateHelpAssistants() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: ROLES_KEY });
    void queryClient.invalidateQueries({ queryKey: TEMPLATES_KEY });
  };
}

function AddHelpAssistant({ templates }: { templates: HelperTemplate[] }) {
  const t = useTranslations();
  const invalidate = useInvalidateHelpAssistants();

  const install = useMutation({
    mutationFn: (kind: HelperKind) =>
      unwrap(
        browserApi.POST("/api/v1/admin/help-assistants/roles/{kind}/", {
          params: { path: { kind } }
        })
      ),
    onSuccess: invalidate,
    onError: (error) => toastApiError(error, t)
  });

  const noneAvailable = templates.length === 0;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          disabled={noneAvailable || install.isPending}
          title={noneAvailable ? t("admin_help_assistants_add_none_available") : undefined}
        >
          <Plus className="size-4" />
          {t("admin_help_assistants_add_button")}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80 max-w-[calc(100vw-2rem)]">
        <DropdownMenuLabel>{t("admin_help_assistants_add_menu_label")}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {templates.map((template) => (
          <DropdownMenuItem
            key={template.kind}
            className="flex cursor-pointer flex-col items-start gap-0.5 whitespace-normal"
            onClick={() => install.mutate(template.kind)}
          >
            <span className="font-medium">{template.name}</span>
            <span className="text-muted-foreground text-xs leading-snug">
              {template.description}
            </span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function HelpAssistantRow({ role }: { role: RoleAssignment }) {
  const t = useTranslations();
  const invalidate = useInvalidateHelpAssistants();
  const kind = role.kind;
  const displayName = role.assistant_name ?? roleKindLabel(kind, t);

  const uninstall = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.DELETE("/api/v1/admin/help-assistants/roles/{kind}/", {
          params: { path: { kind } }
        })
      ),
    onSuccess: invalidate,
    onError: (error) => toastApiError(error, t)
  });
  const toggleEnabled = useMutation({
    mutationFn: (value: boolean) =>
      unwrap(
        browserApi.PATCH("/api/v1/admin/help-assistants/roles/{kind}/enabled", {
          params: { path: { kind } },
          body: { value }
        })
      ),
    onSuccess: invalidate,
    onError: (error) => toastApiError(error, t)
  });
  const toggleVisible = useMutation({
    mutationFn: (value: boolean) =>
      unwrap(
        browserApi.PATCH("/api/v1/admin/help-assistants/roles/{kind}/visible", {
          params: { path: { kind } },
          body: { value }
        })
      ),
    onSuccess: invalidate,
    onError: (error) => toastApiError(error, t)
  });

  return (
    <div className="border-b last:border-b-0">
      <div className="flex items-center gap-3 px-4 py-3">
        <span className="bg-secondary text-secondary-foreground grid size-9 shrink-0 place-items-center rounded-md">
          <Sparkles className="size-4" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{roleKindLabel(kind, t)}</span>
            <Badge variant="secondary">{t("admin_help_assistants_kind_badge")}</Badge>
          </div>
          <p className="text-muted-foreground truncate text-sm">{displayName}</p>
        </div>
        <Button asChild variant="outline" size="sm">
          <Link href={`/admin/help-assistants/${kind}`}>
            {t("admin_help_assistants_open_settings")}
            <ChevronRight className="size-4" />
          </Link>
        </Button>
      </div>

      <div className="bg-muted/20 flex flex-col gap-4 border-t px-4 py-4">
        <Label className="flex items-center justify-between gap-4 font-normal">
          <span className="flex flex-col gap-0.5">
            <span className="font-medium">{t("admin_help_assistants_toggle_enabled")}</span>
            <span className="text-muted-foreground text-sm">
              {t("admin_help_assistants_toggle_enabled_description")}
            </span>
          </span>
          <Switch
            checked={role.is_enabled}
            disabled={toggleEnabled.isPending}
            onCheckedChange={(value) => toggleEnabled.mutate(value)}
          />
        </Label>
        <Label className="flex items-center justify-between gap-4 font-normal">
          <span className="flex flex-col gap-0.5">
            <span className="font-medium">{t("admin_help_assistants_toggle_visible")}</span>
            <span className="text-muted-foreground text-sm">
              {t("admin_help_assistants_toggle_visible_description")}
            </span>
          </span>
          <Switch
            checked={role.is_visible_to_users}
            disabled={toggleVisible.isPending}
            onCheckedChange={(value) => toggleVisible.mutate(value)}
          />
        </Label>
        <div className="flex justify-end">
          <ConfirmDialog
            trigger={
              <Button type="button" variant="outline" size="sm" disabled={uninstall.isPending}>
                {t("admin_help_assistants_delete_button")}
              </Button>
            }
            title={t("admin_help_assistants_delete_button")}
            description={t("admin_help_assistants_delete_confirm", { name: displayName })}
            confirmLabel={t("admin_help_assistants_delete_button")}
            pending={uninstall.isPending}
            onConfirm={() => uninstall.mutateAsync()}
          />
        </div>
      </div>
    </div>
  );
}

export function HelpAssistantsPage() {
  const t = useTranslations();
  const { data: roles } = useSuspenseQuery(helpRolesQueryOptions(browserApi));
  const { data: templates } = useSuspenseQuery(helpTemplatesQueryOptions(browserApi));
  const [filter, setFilter] = useState("");

  const normalizedFilter = filter.trim().toLowerCase();
  const filteredRoles = roles.filter((role) => {
    const haystack = `${role.assistant_name ?? ""} ${roleKindLabel(role.kind, t)}`.toLowerCase();
    return haystack.includes(normalizedFilter);
  });

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
      <PageHeader title={t("admin_help_assistants_page_title")}>
        <AddHelpAssistant templates={templates} />
      </PageHeader>
      <p className="text-muted-foreground max-w-3xl">{t("admin_help_assistants_page_intro")}</p>

      {roles.length === 0 ? (
        <div className="text-muted-foreground rounded-md border border-dashed px-5 py-10 text-center">
          {t("admin_help_assistants_roles_empty")}
        </div>
      ) : (
        <>
          <Input
            value={filter}
            placeholder={t("admin_help_assistants_filter_placeholder")}
            className="max-w-md"
            aria-label={t("admin_help_assistants_filter_placeholder")}
            onChange={(event) => setFilter(event.target.value)}
          />
          {filteredRoles.length === 0 ? (
            <div className="text-muted-foreground rounded-md border border-dashed px-5 py-10 text-center">
              {t("admin_help_assistants_filter_empty")}
            </div>
          ) : (
            <div className="overflow-hidden rounded-md border">
              {filteredRoles.map((role) => (
                <HelpAssistantRow key={role.id} role={role} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
