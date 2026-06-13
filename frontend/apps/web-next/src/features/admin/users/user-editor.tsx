"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { rolesQueryOptions, type AdminUser, type Role } from "./users";

function RolePicker({
  selected,
  onToggle
}: {
  selected: Set<string>;
  onToggle: (roleId: string, checked: boolean) => void;
}) {
  const t = useTranslations();
  const { data } = useQuery(rolesQueryOptions(browserApi));
  const groups: { label: string; roles: Role[] }[] = [
    { label: t("default_roles"), roles: data?.predefined ?? [] },
    { label: t("custom_roles"), roles: data?.custom ?? [] }
  ];

  return (
    <div className="flex flex-col gap-3">
      <Label>{t("roles_permissions")}</Label>
      {groups.map(
        (group) =>
          group.roles.length > 0 && (
            <div key={group.label} className="flex flex-col gap-2">
              <p className="text-muted-foreground text-xs font-medium">{group.label}</p>
              {group.roles.map((role) => (
                <Label
                  key={role.id}
                  className="flex items-center gap-2 font-normal"
                  htmlFor={`role-${role.id}`}
                >
                  <Checkbox
                    id={`role-${role.id}`}
                    checked={selected.has(role.id)}
                    onCheckedChange={(checked) => onToggle(role.id, checked === true)}
                  />
                  {role.name}
                </Label>
              ))}
            </div>
          )
      )}
    </div>
  );
}

/**
 * Form body, mounted fresh each time the dialog opens so its initial values
 * seed from the target user without a reset effect.
 */
function UserEditorForm({ user, onDone }: { user?: AdminUser; onDone: () => void }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const mode = user ? "update" : "create";

  const [email, setEmail] = useState(user?.email ?? "");
  const [username, setUsername] = useState(user?.username ?? "");
  const [password, setPassword] = useState("");
  const [roleIds, setRoleIds] = useState<Set<string>>(
    new Set((user?.roles ?? []).map((role) => role.id))
  );

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["admin-users"] });

  const create = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/admin/users/", {
          body: {
            email: email.trim(),
            username: username.trim() || null,
            password,
            roles: [...roleIds].map((id) => ({ id }))
          }
        })
      ),
    onSuccess: () => {
      invalidate();
      onDone();
    },
    onError: (error) => toastApiError(error, t)
  });

  const updateUser = useMutation({
    mutationFn: () => {
      if (!user?.username) throw new Error("missing username");
      return unwrap(
        browserApi.POST("/api/v1/admin/users/{username}/", {
          params: { path: { username: user.username } },
          body: {
            email: email.trim(),
            password: password || undefined,
            roles: [...roleIds].map((id) => ({ id }))
          }
        })
      );
    },
    onSuccess: () => {
      invalidate();
      onDone();
    },
    onError: (error) => toastApiError(error, t)
  });

  const pending = create.isPending || updateUser.isPending;

  function submit() {
    if (mode === "create") {
      if (!username.trim() || !email.trim() || !password) {
        toast.warning(t("required_field"));
        return;
      }
      create.mutate();
    } else {
      if (!user?.username) {
        toast.warning(t("cant_edit_user_without_username"));
        return;
      }
      updateUser.mutate();
    }
  }

  return (
    <DialogContent className="max-h-[85vh] overflow-y-auto">
      <DialogHeader>
        <DialogTitle>{mode === "create" ? t("create_a_new_user") : t("edit_user")}</DialogTitle>
        <DialogDescription>
          {mode === "create" ? t("create_a_new_user") : t("edit_the_selected_user")}
        </DialogDescription>
      </DialogHeader>

      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <Label htmlFor="user-username">{t("username")}</Label>
          <Input
            id="user-username"
            value={username}
            disabled={mode === "update"}
            onChange={(event) => setUsername(event.target.value)}
          />
          <p className="text-muted-foreground text-xs">
            {mode === "update"
              ? t("username_change_logout_hint")
              : t("unique_username_description")}
          </p>
        </div>

        <div className="flex flex-col gap-2">
          <Label htmlFor="user-email">{t("email")}</Label>
          <Input
            id="user-email"
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </div>

        <div className="flex flex-col gap-2">
          <Label htmlFor="user-password">{t("password")}</Label>
          <Input
            id="user-password"
            type="password"
            autoComplete="off"
            value={password}
            placeholder={mode === "update" ? "••••••••" : undefined}
            onChange={(event) => setPassword(event.target.value)}
          />
          <p className="text-muted-foreground text-xs">{t("password_needs_7_chars")}</p>
        </div>

        <RolePicker
          selected={roleIds}
          onToggle={(roleId, checked) =>
            setRoleIds((current) => {
              const next = new Set(current);
              if (checked) next.add(roleId);
              else next.delete(roleId);
              return next;
            })
          }
        />
      </div>

      <DialogFooter>
        <Button variant="outline" disabled={pending} onClick={onDone}>
          {t("cancel")}
        </Button>
        <Button disabled={pending} onClick={submit}>
          {pending ? t("loading") : mode === "create" ? t("create_user") : t("save_changes")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

/**
 * Create or edit a user. Update targets POST /api/v1/admin/users/{username}/
 * (username cannot change). User-groups assignment is dropped with the legacy
 * area (OQ-2); role assignment is kept.
 */
export function UserEditorDialog({
  open,
  onOpenChange,
  user
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Omitted → create mode. */
  user?: AdminUser;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {open && <UserEditorForm user={user} onDone={() => onOpenChange(false)} />}
    </Dialog>
  );
}
