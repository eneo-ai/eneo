"use client";

import { useMutation, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { PageHeader } from "@/components/composites/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
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
  helpRolesQueryOptions,
  helpTemplatesQueryOptions
} from "@/features/admin/help-assistants/help-assistants";

function HelperCard({ template, role }: { template: HelperTemplate; role?: RoleAssignment }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const kind = template.kind;
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ROLES_KEY });

  const install = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/admin/help-assistants/roles/{kind}/", {
          params: { path: { kind } }
        })
      ),
    onSuccess: invalidate,
    onError: (error) => toastApiError(error, t)
  });
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
    <Card className="flex flex-col gap-4 p-5">
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-1">
          <span className="font-medium">{template.name}</span>
          <p className="text-muted-foreground text-sm">{template.description}</p>
        </div>
        <Badge variant={role ? "default" : "outline"}>
          {role ? t("help_assistant_installed") : t("help_assistant_available")}
        </Badge>
      </div>

      {role ? (
        <div className="flex flex-col gap-3">
          <Label className="flex items-center justify-between gap-2 font-normal">
            {t("enabled")}
            <Switch
              checked={role.is_enabled}
              disabled={toggleEnabled.isPending}
              onCheckedChange={(value) => toggleEnabled.mutate(value)}
            />
          </Label>
          <Label className="flex items-center justify-between gap-2 font-normal">
            {t("help_assistant_visible_to_users")}
            <Switch
              checked={role.is_visible_to_users}
              disabled={toggleVisible.isPending}
              onCheckedChange={(value) => toggleVisible.mutate(value)}
            />
          </Label>
          <Button
            variant="outline"
            size="sm"
            disabled={uninstall.isPending}
            onClick={() => uninstall.mutate()}
          >
            {t("help_assistant_uninstall")}
          </Button>
        </div>
      ) : (
        <Button size="sm" disabled={install.isPending} onClick={() => install.mutate()}>
          {t("help_assistant_install")}
        </Button>
      )}
    </Card>
  );
}

export function HelpAssistantsPage() {
  const t = useTranslations();
  const { data: roles } = useSuspenseQuery(helpRolesQueryOptions(browserApi));
  const { data: templates } = useSuspenseQuery(helpTemplatesQueryOptions(browserApi));

  const roleByKind = new Map<HelperKind, RoleAssignment>(roles.map((role) => [role.kind, role]));

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
      <PageHeader title={t("admin_help_assistants_nav_label")} />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {templates.map((template) => (
          <HelperCard
            key={template.kind}
            template={template}
            role={roleByKind.get(template.kind)}
          />
        ))}
      </div>
    </div>
  );
}
