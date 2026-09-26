"use client";

import { Button } from "@astryxdesign/core/Button";
import { TextInput } from "@/components/astryx/text-input";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { ConfirmedSecretInput } from "@/components/composites/confirmed-secret-input";
import { LoadingState } from "@/components/composites/loading-state";
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
import { newPasswordErrors, passwordPolicyQueryOptions } from "@/features/auth/password-policy";
import { PasswordPolicyChecklist } from "@/features/auth/password-policy-checklist";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import { rolesQueryOptions, type Role } from "@/features/admin/roles/roles";
import { type AdminUser } from "./users";

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

type Field = "username" | "email" | "policy" | "password" | "confirmation";

/**
 * Form body, mounted fresh each time the dialog opens so its initial values
 * seed from the target user without a reset effect.
 *
 * A password is checked against the backend's local policy (fetched, like
 * SvelteKit's admin users page). Problems show at their fields on submit and
 * focus moves to the first (WCAG 3.3.1); what the backend refuses about a
 * password shows at the password field.
 */
function UserEditorForm({ user, onDone }: { user?: AdminUser; onDone: () => void }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const formId = useId();
  const checklistId = useId();
  const mode = user ? "update" : "create";
  const policyQuery = useQuery(passwordPolicyQueryOptions(browserApi));
  const policy = policyQuery.data ?? null;

  const [email, setEmail] = useState(user?.email ?? "");
  const [username, setUsername] = useState(user?.username ?? "");
  const [password, setPassword] = useState("");
  const [passwordConfirmation, setPasswordConfirmation] = useState("");
  const [roleIds, setRoleIds] = useState<Set<string>>(
    new Set((user?.roles ?? []).map((role) => role.id))
  );
  const [submitted, setSubmitted] = useState(false);
  /** What the backend refused about the password, until it is edited. */
  const [refused, setRefused] = useState<string>();
  const usernameRef = useRef<HTMLInputElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const retryRef = useRef<HTMLButtonElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const confirmationRef = useRef<HTMLInputElement>(null);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["admin-users"] });

  // A password the backend refuses is said at its field; the rest is toasted.
  function onError(error: Error) {
    const code = error instanceof EneoApiError ? error.code : undefined;
    const message =
      code === 9058
        ? t("password_must_be_different")
        : code === 9059
          ? t("password_policy_rejected")
          : undefined;
    if (message) {
      flushSync(() => setRefused(message));
      passwordRef.current?.focus();
    } else {
      toastApiError(error, t);
    }
  }

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
    onError
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
    onError
  });

  const pending = create.isPending || updateUser.isPending;
  const policyUnavailable = !policyQuery.isPending && policy === null;
  const pair = policy
    ? newPasswordErrors(t, {
        password,
        confirmation: passwordConfirmation,
        policy,
        required: mode === "create"
      })
    : {};
  const errors: Record<Field, string | undefined> = {
    username:
      mode === "create" && !username.trim() ? t("admin_users_username_required") : undefined,
    email: email.trim() ? undefined : t("admin_users_email_required"),
    // A new account needs a password, which cannot be checked without the policy.
    policy: mode === "create" && policyUnavailable ? t("password_policy_unavailable") : undefined,
    password: pair.password ?? refused,
    confirmation: pair.confirmation
  };
  const shown = (field: Field) => (submitted ? errors[field] : undefined);
  const fields: Record<Field, React.RefObject<HTMLElement | null>> = {
    username: usernameRef,
    email: emailRef,
    policy: retryRef,
    password: passwordRef,
    confirmation: confirmationRef
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
    if (mode === "create") {
      create.mutate();
    } else if (!user?.username) {
      toast.warning(t("cant_edit_user_without_username"));
    } else {
      updateUser.mutate();
    }
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
        ) : (
          <>
            <PasswordPolicyChecklist
              id={checklistId}
              password={password}
              confirmation={passwordConfirmation}
              policy={policy}
            />
            <ConfirmedSecretInput
              label={t("password")}
              confirmLabel={t("confirm_password")}
              description={mode === "update" ? t("admin_password_optional_hint") : undefined}
              describedBy={checklistId}
              value={password}
              confirmation={passwordConfirmation}
              onValueChange={(value) => {
                setPassword(value);
                setRefused(undefined);
              }}
              onConfirmationChange={setPasswordConfirmation}
              isRequired={mode === "create"}
              // Someone else's password: never the admin's own, and a password
              // manager may offer a generated one.
              autoComplete="new-password"
              valueError={submitted ? errors.password : refused}
              mismatchMessage={errors.confirmation ?? t("change_password_mismatch")}
              showErrors={submitted}
              valueRef={passwordRef}
              confirmationRef={confirmationRef}
            />
          </>
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
          <Button label={t("cancel")} isDisabled={pending} onClick={onDone} />
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
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {open && <UserEditorForm user={user} onDone={() => onOpenChange(false)} />}
    </Dialog>
  );
}
