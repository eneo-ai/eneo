"use client";

import { Button } from "@astryxdesign/core/Button";
import { Switch } from "@astryxdesign/core/Switch";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { generatePassword } from "@eneo/eneo-js/auth/password-generator";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { LoadingState } from "@/components/composites/loading-state";
import { SecretRevealDialog } from "@/components/composites/secret-reveal";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { passwordPolicyQueryOptions } from "@/features/auth/password-policy";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import { rolesQueryOptions, type Role } from "@/features/admin/roles/roles";
import type { AdminUser } from "./users";

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

type Field = "username" | "email" | "policy";

/** A password the backend has just set, for the one-time display. */
type IssuedPassword = { password: string; email: string };

/**
 * Form body, mounted fresh each time the dialog opens so its initial values
 * seed from the target user without a reset effect.
 *
 * Admins never type a password: a new account, or an existing one whose
 * password is replaced, gets one generated against the backend's local policy
 * (fetched, like SvelteKit's admin users page), so a policy change needs no
 * change here. Problems show at their fields on submit and focus moves to the
 * first (WCAG 3.3.1).
 */
function UserEditorForm({
  user,
  onDone
}: {
  user?: AdminUser;
  onDone: (issued?: IssuedPassword) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const formId = useId();
  const mode = user ? "update" : "create";
  const policyQuery = useQuery(passwordPolicyQueryOptions(browserApi));
  const policy = policyQuery.data ?? null;
  const oneTimeHint = ` ${t("admin_password_one_time_hint")}`;

  const [email, setEmail] = useState(user?.email ?? "");
  const [username, setUsername] = useState(user?.username ?? "");
  const [replacePassword, setReplacePassword] = useState(false);
  const [roleIds, setRoleIds] = useState<Set<string>>(
    new Set((user?.roles ?? []).map((role) => role.id))
  );
  const [submitted, setSubmitted] = useState(false);
  const usernameRef = useRef<HTMLInputElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const retryRef = useRef<HTMLButtonElement>(null);

  // A set password is handed over first; the list refreshes once it is closed.
  function finish(password: string | null) {
    if (password) {
      onDone({ password, email: email.trim() });
    } else {
      void queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      onDone();
    }
  }

  const create = useMutation({
    mutationFn: (password: string) =>
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
    onSuccess: (_, password) => finish(password),
    onError: (error) => toastApiError(error, t)
  });

  const updateUser = useMutation({
    mutationFn: (password: string | null) => {
      if (!user?.username) throw new Error("missing username");
      return unwrap(
        browserApi.POST("/api/v1/admin/users/{username}/", {
          params: { path: { username: user.username } },
          body: {
            email: email.trim(),
            password: password ?? undefined,
            roles: [...roleIds].map((id) => ({ id }))
          }
        })
      );
    },
    onSuccess: (_, password) => finish(password),
    onError: (error) => toastApiError(error, t)
  });

  const pending = create.isPending || updateUser.isPending;
  const needsPassword = mode === "create" || replacePassword;
  const policyUnavailable = !policyQuery.isPending && policy === null;
  const errors: Record<Field, string | undefined> = {
    username:
      mode === "create" && !username.trim() ? t("admin_users_username_required") : undefined,
    email: email.trim() ? undefined : t("admin_users_email_required"),
    // A password is drawn against the policy, so none can be set without it.
    policy: needsPassword && policyUnavailable ? t("password_policy_unavailable") : undefined
  };
  const shown = (field: Field) => (submitted ? errors[field] : undefined);
  const fields: Record<Field, React.RefObject<HTMLElement | null>> = {
    username: usernameRef,
    email: emailRef,
    policy: retryRef
  };

  function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending || policyQuery.isPending) return;
    const first = (Object.keys(errors) as Field[]).find((field) => errors[field]);
    if (first) {
      // Rendered before focus moves, so the field is read with its error.
      flushSync(() => setSubmitted(true));
      fields[first].current?.focus();
      return;
    }
    if (mode === "update" && !user?.username) {
      toast.warning(t("cant_edit_user_without_username"));
      return;
    }
    let password: string | null = null;
    if (needsPassword && policy) {
      try {
        password = generatePassword(policy);
      } catch {
        // The backend sent a policy no password can meet.
        toast.error(t("admin_password_policy_unsatisfiable"));
        return;
      }
    }
    if (mode === "update") updateUser.mutate(password);
    else if (password) create.mutate(password);
  }

  const usernameError = shown("username");
  const emailError = shown("email");

  return (
    <DialogContent className="max-h-[85vh] overflow-y-auto">
      <DialogHeader>
        <DialogTitle>{mode === "create" ? t("create_a_new_user") : t("edit_user")}</DialogTitle>
        <DialogDescription>
          {mode === "create" ? t("create_a_new_user") : t("edit_the_selected_user")}
        </DialogDescription>
      </DialogHeader>

      <form id={formId} className="flex flex-col gap-4" noValidate onSubmit={submit}>
        <TextInput
          ref={usernameRef}
          label={t("username")}
          description={
            mode === "update" ? t("username_change_logout_hint") : t("unique_username_description")
          }
          value={username}
          onChange={setUsername}
          isRequired={mode === "create"}
          isDisabled={mode === "update"}
          autoComplete="off"
          status={usernameError ? { type: "error", message: usernameError } : undefined}
        />
        <TextInput
          ref={emailRef}
          type="email"
          label={t("email")}
          value={email}
          onChange={setEmail}
          isRequired
          autoComplete="off"
          status={emailError ? { type: "error", message: emailError } : undefined}
        />

        {policyQuery.isPending ? (
          <LoadingState rows={2} label={t("loading")} />
        ) : policy === null ? (
          <div className="flex flex-col items-start gap-2">
            <p className="text-ax-error text-sm">{t("password_policy_unavailable")}</p>
            <Button
              ref={retryRef}
              label={t("retry")}
              size="sm"
              isLoading={policyQuery.isFetching}
              isInterruptible
              onClick={() => {
                if (!policyQuery.isFetching) void policyQuery.refetch();
              }}
            />
          </div>
        ) : mode === "create" ? (
          <div className="flex flex-col gap-1">
            <Text type="label" display="block">
              {t("password")}
            </Text>
            <Text type="supporting">{t("admin_password_generated_hint") + oneTimeHint}</Text>
          </div>
        ) : (
          <Switch
            label={t("admin_password_replace")}
            description={t("admin_password_replace_desc") + oneTimeHint}
            labelPosition="start"
            labelSpacing="spread"
            value={replacePassword}
            onChange={setReplacePassword}
          />
        )}

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

        <DialogFooter>
          <Button label={t("cancel")} isDisabled={pending} onClick={() => onDone()} />
          <Button
            type="submit"
            variant="primary"
            label={mode === "create" ? t("create_user") : t("save_changes")}
            // Keeps focus while saving; a second press is ignored above.
            isLoading={pending}
            isInterruptible
          />
        </DialogFooter>
      </form>
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
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [issued, setIssued] = useState<IssuedPassword | null>(null);

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        {open && (
          <UserEditorForm
            user={user}
            onDone={(next) => {
              onOpenChange(false);
              if (next) setIssued(next);
            }}
          />
        )}
      </Dialog>
      <SecretRevealDialog
        title={user ? t("admin_password_replaced_title") : t("admin_user_created_title")}
        secret={issued?.password ?? null}
        warning={
          issued
            ? `${t("admin_issued_password_handover", { email: issued.email })} ${t("admin_password_one_time_hint")}`
            : undefined
        }
        copyFailedMessage={t("admin_issued_password_copy_failed")}
        onClose={() => {
          setIssued(null);
          void queryClient.invalidateQueries({ queryKey: ["admin-users"] });
        }}
      />
    </>
  );
}
