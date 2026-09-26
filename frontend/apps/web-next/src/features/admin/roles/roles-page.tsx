"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Minus, Pencil, Plus, RotateCcw, Search, Star, Trash2, Users } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useState, type SubmitEvent } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { PageHeader } from "@/components/composites/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
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
import { browserApi } from "@/lib/api/browser";
import { getErrorMessage, unwrap } from "@/lib/api/errors";
import { toast } from "@/lib/toast";
import { useAppContext } from "@/components/providers/app-context";
import {
  groupPermissions,
  permissionsQueryOptions,
  roleMatches,
  rolesQueryOptions,
  ROLES_KEY,
  sameSet,
  sortRoles,
  templatesQueryOptions,
  type Permission,
  type PermissionEntry,
  type PermissionGroup,
  type Role
} from "./roles";

const GROUP_KEYS = {
  chat: { label: "permission_group_chat", short: "permission_group_chat_short" },
  build: { label: "permission_group_build", short: "permission_group_build_short" },
  knowledge: { label: "permission_group_knowledge", short: "permission_group_knowledge_short" },
  insight: { label: "permission_group_insight", short: "permission_group_insight_short" },
  admin: { label: "permission_group_admin", short: "permission_group_admin_short" },
  other: { label: "permission_group_other", short: "permission_group_other_short" }
} as const;
const PERMISSION_KEYS: Partial<Record<Permission, string>> = {
  assistants: "permission_assistants",
  skills: "permission_skills",
  skills_management: "permission_skills_management",
  personal_chat: "permission_personal_chat",
  group_chats: "permission_group_chats",
  apps: "permission_apps",
  services: "permission_services",
  collections: "permission_collections",
  websites: "permission_websites",
  insights: "permission_insights",
  integrations: "permission_integrations",
  AI: "permission_ai",
  admin: "permission_admin",
  shared_spaces: "permission_shared_spaces",
  api_keys: "permission_api_keys",
  modules: "permission_modules",
  storage: "permission_storage",
  assistant_debug: "permission_assistant_debug",
  web_search: "permission_web_search",
  image_generation: "permission_image_generation"
};

type Editor = { kind: "create" } | { kind: "update"; role: Role };
type PendingAction = { kind: "delete" | "reset" | "default"; role: Role };

export function RolesPage() {
  const t = useTranslations();
  const locale = useLocale();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { tenant } = useAppContext();
  const [defaultRoleId, setDefaultRoleId] = useState(tenant.default_role_id ?? null);
  const [query, setQuery] = useState("");
  const [editor, setEditor] = useState<Editor | null>(null);
  const [name, setName] = useState("");
  const [selected, setSelected] = useState<Permission[]>([]);
  const [saving, setSaving] = useState(false);
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [actionBusy, setActionBusy] = useState(false);

  const rolesQuery = useQuery(rolesQueryOptions(browserApi));
  const permissionsQuery = useQuery(permissionsQueryOptions(browserApi));
  const templatesQuery = useQuery({
    ...templatesQueryOptions(browserApi, permissionsQuery.data ?? []),
    enabled: permissionsQuery.isSuccess
  });

  const groups = groupPermissions(permissionsQuery.data ?? []);
  const allRoles = [...(rolesQuery.data?.custom ?? []), ...(rolesQuery.data?.predefined ?? [])];
  const defaultRole = allRoles.find((role) => role.id === defaultRoleId);
  const permissionLabel = (entry: PermissionEntry) => {
    const key = PERMISSION_KEYS[entry.name];
    return key
      ? t(key as Parameters<typeof t>[0])
      : entry.name.replace(/_/g, " ").replace(/^./, (char) => char.toUpperCase());
  };
  const permissionDescription = (entry: PermissionEntry) => {
    const key = PERMISSION_KEYS[entry.name];
    return key ? t(`${key}_description` as Parameters<typeof t>[0]) : entry.description;
  };
  const groupLabel = (group: PermissionGroup) => t(GROUP_KEYS[group.id].label);
  const visible = sortRoles(allRoles, defaultRoleId, locale).filter((role) =>
    roleMatches(role, groups, query, permissionLabel)
  );

  function openEditor(next: Editor) {
    setName(next.kind === "update" ? next.role.name : "");
    setSelected(next.kind === "update" ? [...next.role.permissions] : []);
    setEditor(next);
  }

  function setPermission(permission: Permission, checked: boolean) {
    setSelected((current) =>
      checked
        ? [...new Set([...current, permission])]
        : current.filter((item) => item !== permission)
    );
  }

  function setGroup(group: PermissionGroup, checked: boolean) {
    const names = group.permissions.map((entry) => entry.name);
    setSelected((current) =>
      checked
        ? [...new Set([...current, ...names])]
        : current.filter((item) => !names.includes(item))
    );
  }

  const editingRole = editor?.kind === "update" ? editor.role : null;
  const nameChanged = name.trim() !== (editingRole?.name ?? "").trim();
  const permissionsChanged = !sameSet(selected, editingRole?.permissions ?? []);
  const canSubmit =
    !saving &&
    name.trim().length > 0 &&
    (editor?.kind === "create" || nameChanged || permissionsChanged);

  async function saveRole(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editor || !canSubmit) return;
    setSaving(true);
    const trimmed = name.trim();
    try {
      if (editor.kind === "create") {
        await unwrap(
          browserApi.POST("/api/v1/roles/", {
            body: { name: trimmed, permissions: selected }
          })
        );
        toast.success(t("roles_created_toast", { name: trimmed }));
      } else {
        await unwrap(
          browserApi.POST("/api/v1/roles/{role_id}/", {
            params: { path: { role_id: editor.role.id } },
            body: {
              ...(nameChanged ? { name: trimmed } : {}),
              ...(permissionsChanged ? { permissions: selected } : {})
            }
          })
        );
        toast.success(t("roles_saved_toast", { name: trimmed }));
      }
      setEditor(null);
      await queryClient.invalidateQueries({ queryKey: ROLES_KEY });
    } catch (error) {
      toast.error(getErrorMessage(error, t));
    } finally {
      setSaving(false);
    }
  }

  async function runPending() {
    if (!pending || actionBusy) return;
    setActionBusy(true);
    const { kind, role } = pending;
    try {
      if (kind === "delete") {
        await unwrap(
          browserApi.DELETE("/api/v1/roles/{role_id}/", {
            params: { path: { role_id: role.id } }
          })
        );
        toast.success(t("roles_deleted_toast", { name: role.name }));
      } else if (kind === "reset") {
        await unwrap(
          browserApi.POST("/api/v1/roles/{role_id}/reset/", {
            params: { path: { role_id: role.id } }
          })
        );
        toast.success(t("roles_reset_toast", { name: role.name }));
      } else {
        await unwrap(
          browserApi.POST("/api/v1/roles/{role_id}/set-default/", {
            params: { path: { role_id: role.id } }
          })
        );
        setDefaultRoleId(role.id);
        router.refresh();
        toast.success(t("roles_default_toast", { name: role.name }));
      }
      setPending(null);
      await queryClient.invalidateQueries({ queryKey: ROLES_KEY });
    } catch (error) {
      toast.error(getErrorMessage(error, t));
    } finally {
      setActionBusy(false);
    }
  }

  const failed = rolesQuery.isError || permissionsQuery.isError || templatesQuery.isError;
  const loading = rolesQuery.isPending || permissionsQuery.isPending || templatesQuery.isPending;
  const pendingCopy = pending
    ? {
        title:
          pending.kind === "delete"
            ? t("delete_role")
            : pending.kind === "reset"
              ? t("reset_to_template")
              : t("set_as_default_role"),
        description:
          pending.kind === "delete"
            ? t("roles_delete_description", { name: pending.role.name })
            : pending.kind === "reset"
              ? t("reset_to_template_description", { name: pending.role.name })
              : t("set_as_default_role_description", { name: pending.role.name }),
        label:
          pending.kind === "delete"
            ? t("delete")
            : pending.kind === "reset"
              ? t("reset")
              : t("confirm")
      }
    : null;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 pb-16">
      <PageHeader title={t("roles")} tour="admin-roles">
        <Button onClick={() => openEditor({ kind: "create" })} disabled={failed || loading}>
          <Plus className="size-4" />
          {t("create_role")}
        </Button>
      </PageHeader>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="text-muted-foreground max-w-3xl space-y-1 text-sm">
          <p>
            {t("roles_page_description")} {t("roles_template_note")}
          </p>
          <p>
            {defaultRole
              ? t("roles_default_role_note", { name: defaultRole.name })
              : t("roles_no_default_role_note")}
          </p>
        </div>
        <div className="relative w-full sm:w-72">
          <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
          <Input
            type="search"
            className="pl-9"
            aria-label={t("roles_search_label")}
            placeholder={t("roles_search_placeholder")}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
      </div>
      {failed ? (
        <Alert variant="destructive" role="alert">
          <AlertTitle>{t("request_failed")}</AlertTitle>
          <AlertDescription>
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                void rolesQuery.refetch();
                void permissionsQuery.refetch();
                void templatesQuery.refetch();
              }}
            >
              {t("retry")}
            </Button>
          </AlertDescription>
        </Alert>
      ) : loading ? (
        <p role="status" className="text-muted-foreground text-sm">
          {t("loading")}
        </p>
      ) : (
        <div className="divide-y rounded-xl border" role="list" aria-label={t("roles")}>
          {visible.length === 0 ? (
            <p className="p-5 text-sm" role="status">
              {t("roles_no_match", { query })}
            </p>
          ) : (
            visible.map((role) => (
              <RoleRow
                key={role.id}
                role={role}
                groups={groups}
                isDefault={role.id === defaultRoleId}
                labelFor={permissionLabel}
                groupLabel={groupLabel}
                onEdit={() => openEditor({ kind: "update", role })}
                onAction={(kind) => setPending({ kind, role })}
              />
            ))
          )}
        </div>
      )}

      <Dialog
        open={editor !== null}
        onOpenChange={(open) => {
          if (!open && !saving) setEditor(null);
        }}
      >
        <DialogContent
          showCloseButton={!saving}
          className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-2xl"
        >
          <DialogHeader>
            <DialogTitle>
              {t(editor?.kind === "create" ? "create_a_new_role" : "edit_role")}
            </DialogTitle>
            <DialogDescription>{t("what_users_of_this_role_can_manage")}</DialogDescription>
          </DialogHeader>
          <form className="space-y-5" onSubmit={(event) => void saveRole(event)} aria-busy={saving}>
            <fieldset disabled={saving} className="space-y-5">
              <div className="space-y-1.5">
                <Label htmlFor="role-name">{t("role_name")}</Label>
                <Input
                  id="role-name"
                  required
                  autoComplete="off"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                />
                <p className="text-muted-foreground text-xs">
                  {t("descriptive_name_for_this_role")}
                </p>
              </div>
              {editor?.kind === "create" &&
                templatesQuery.data &&
                templatesQuery.data.length > 0 && (
                  <div>
                    <p className="text-sm font-medium">{t("start_from_template")}</p>
                    <p className="text-muted-foreground text-sm">{t("roles_template_hint")}</p>
                    <div
                      className="mt-2 flex flex-wrap gap-2"
                      role="group"
                      aria-label={t("start_from_template")}
                    >
                      {templatesQuery.data.map((template) => (
                        <Button
                          key={template.name}
                          type="button"
                          size="sm"
                          variant={
                            sameSet(selected, template.permissions) ? "secondary" : "outline"
                          }
                          aria-pressed={sameSet(selected, template.permissions)}
                          onClick={() => setSelected([...template.permissions])}
                        >
                          {template.name}
                        </Button>
                      ))}
                    </div>
                  </div>
                )}
              <div className="space-y-3">
                <p className="text-sm font-medium">{t("included_permissions")}</p>
                {groups.map((group) => {
                  const granted = group.permissions.filter((entry) =>
                    selected.includes(entry.name)
                  ).length;
                  const all = granted === group.permissions.length;
                  return (
                    <fieldset key={group.id} className="overflow-hidden rounded-lg border">
                      <legend className="sr-only">{groupLabel(group)}</legend>
                      <div className="bg-muted/40 flex items-center justify-between gap-3 border-b px-3 py-2">
                        <span className="text-sm font-medium">
                          {groupLabel(group)}{" "}
                          <span className="text-muted-foreground tabular-nums">
                            {granted}/{group.permissions.length}
                          </span>
                        </span>
                        <label className="flex items-center gap-2 text-xs">
                          <span>{t("roles_select_all")}</span>
                          <input
                            type="checkbox"
                            className="accent-primary size-4"
                            checked={all}
                            aria-label={t("roles_select_all_in_group", {
                              group: groupLabel(group)
                            })}
                            onChange={(event) => setGroup(group, event.target.checked)}
                          />
                        </label>
                      </div>
                      <div className="divide-y">
                        {group.permissions.map((entry) => (
                          <label
                            key={entry.name}
                            className="flex items-start justify-between gap-4 px-3 py-2.5"
                          >
                            <span>
                              <span className="block text-sm font-medium">
                                {permissionLabel(entry)}
                              </span>
                              <span className="text-muted-foreground block text-xs">
                                {permissionDescription(entry)}
                              </span>
                            </span>
                            <input
                              type="checkbox"
                              className="accent-primary mt-1 size-4 shrink-0"
                              checked={selected.includes(entry.name)}
                              onChange={(event) => setPermission(entry.name, event.target.checked)}
                            />
                          </label>
                        ))}
                      </div>
                    </fieldset>
                  );
                })}
              </div>
            </fieldset>
            <DialogFooter className="items-center justify-between gap-3">
              <span className="text-muted-foreground text-sm tabular-nums" aria-live="polite">
                {t("permissions_selected_count", {
                  selected: selected.length,
                  total: permissionsQuery.data?.length ?? 0
                })}
              </span>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  disabled={saving}
                  onClick={() => setEditor(null)}
                >
                  {t("cancel")}
                </Button>
                <Button type="submit" disabled={!canSubmit}>
                  {saving
                    ? t("saving")
                    : editor?.kind === "create"
                      ? t("create_role")
                      : t("save_changes")}
                </Button>
              </div>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {pendingCopy && (
        <ConfirmDialogControlled
          open={pending !== null}
          onOpenChange={(open) => {
            if (!open && !actionBusy) setPending(null);
          }}
          title={pendingCopy.title}
          description={pendingCopy.description}
          confirmLabel={pendingCopy.label}
          variant={pending?.kind === "delete" ? "destructive" : "default"}
          pending={actionBusy}
          onConfirm={() => void runPending()}
        />
      )}
    </div>
  );
}

function RoleRow({
  role,
  groups,
  isDefault,
  labelFor,
  groupLabel,
  onEdit,
  onAction
}: {
  role: Role;
  groups: PermissionGroup[];
  isDefault: boolean;
  labelFor: (entry: PermissionEntry) => string;
  groupLabel: (group: PermissionGroup) => string;
  onEdit: () => void;
  onAction: (kind: PendingAction["kind"]) => void;
}) {
  const t = useTranslations();
  const granted = new Set(role.permissions);
  return (
    <article role="listitem" className="space-y-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-semibold">{role.name}</h2>
            {isDefault && (
              <Badge>
                <Star className="size-3" />
                {t("roles_default_badge")}
              </Badge>
            )}
            {role.predefined_source && (
              <Badge
                variant="outline"
                title={t("roles_template_badge_tooltip", { name: role.predefined_source })}
              >
                {t("roles_template_badge_named", { name: role.predefined_source })}
              </Badge>
            )}
          </div>
          <ul className="flex flex-wrap gap-1.5" aria-label={t("roles_group_summary_label")}>
            {groups.map((group) => {
              const count = group.permissions.filter((entry) => granted.has(entry.name)).length;
              return (
                <li key={group.id}>
                  <Badge variant={count === group.permissions.length ? "secondary" : "outline"}>
                    {count === group.permissions.length ? (
                      <Check className="size-3" />
                    ) : count === 0 ? (
                      <Minus className="size-3" />
                    ) : null}
                    {t(GROUP_KEYS[group.id].short)}{" "}
                    <span className="tabular-nums">
                      {count}/{group.permissions.length}
                    </span>
                  </Badge>
                </li>
              );
            })}
          </ul>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={onEdit}>
            <Pencil className="size-4" />
            {t("edit")}
          </Button>
          <Button variant="ghost" size="sm" asChild>
            <Link href={`/admin/users?role_id=${encodeURIComponent(role.id)}`}>
              <Users className="size-4" />
              {t("roles_view_users")}
            </Link>
          </Button>
          {!isDefault && (
            <Button variant="ghost" size="sm" onClick={() => onAction("default")}>
              <Star className="size-4" />
              {t("set_as_default_role")}
            </Button>
          )}
          {role.predefined_source && (
            <Button variant="ghost" size="sm" onClick={() => onAction("reset")}>
              <RotateCcw className="size-4" />
              {t("reset_to_template")}
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            disabled={isDefault}
            title={isDefault ? t("roles_cannot_delete_default") : undefined}
            onClick={() => onAction("delete")}
          >
            <Trash2 className="size-4" />
            {t("delete_role")}
          </Button>
        </div>
      </div>
      <details className="text-sm">
        <summary className="text-muted-foreground cursor-pointer select-none">
          {t("roles_show_permissions", { name: role.name })}
        </summary>
        <div className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {groups.map((group) => (
            <section key={group.id}>
              <h3 className="text-muted-foreground text-xs font-semibold uppercase">
                {groupLabel(group)}
              </h3>
              <ul className="mt-1 space-y-1">
                {group.permissions.map((entry) => (
                  <li
                    key={entry.name}
                    className={`flex items-center gap-1.5 ${granted.has(entry.name) ? "" : "text-muted-foreground"}`}
                  >
                    {granted.has(entry.name) ? (
                      <Check className="size-3.5" />
                    ) : (
                      <Minus className="size-3.5" />
                    )}
                    <span className="sr-only">
                      {t(
                        granted.has(entry.name)
                          ? "roles_permission_included"
                          : "roles_permission_not_included"
                      )}
                    </span>
                    {labelFor(entry)}
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </details>
    </article>
  );
}
