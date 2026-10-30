"use client";

import { Button } from "@astryxdesign/core/Button";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { FormLayout } from "@astryxdesign/core/FormLayout";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { generatePassword } from "@eneo/eneo-js/auth/password-generator";
import { revealProblems } from "@/components/composites/field-problem";
import { DIALOG_TOP_ON_TOUCH } from "@/components/astryx/dialog-placement";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { useId, useRef, useState } from "react";
import { LoadingState } from "@/components/composites/loading-state";
import { SecretRevealDialog } from "@/components/composites/secret-reveal";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { passwordPolicyQueryOptions } from "@/features/auth/password-policy";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import { rolesQueryOptions, type Role } from "@/features/admin/roles/roles";
import { UserGroupField } from "./user-group-field";
import type { AdminUser } from "./users";

/**
 * The roles as checkbox rows in named groups (Standardroller, Anpassade
 * roller), each row a whole 44 px target on touch.
 */
function RolePicker({
  selected,
  onToggle
}: {
  selected: Set<string>;
  onToggle: (roleId: string, checked: boolean) => void;
}) {
  const t = useTranslations();
  const baseId = useId();
  const { data } = useQuery(rolesQueryOptions(browserApi));
  const groups: { key: string; label: string; roles: Role[] }[] = [
    { key: "default", label: t("default_roles"), roles: data?.predefined ?? [] },
    { key: "custom", label: t("custom_roles"), roles: data?.custom ?? [] }
  ];

  return (
    <div className="flex flex-col gap-3">
      <Text type="label" display="block">
        {t("roles_permissions")}
      </Text>
      {groups.map(
        (group) =>
          group.roles.length > 0 && (
            <div
              key={group.key}
              role="group"
              aria-labelledby={`${baseId}-${group.key}`}
              className="flex flex-col"
            >
              <span
                id={`${baseId}-${group.key}`}
                className="text-ax-text-secondary pb-1 text-xs font-medium"
              >
                {group.label}
              </span>
              {group.roles.map((role) => (
                // The label's ::after covers the row: the tap target is the
                // row, not the words (the theme makes it 44 px on touch).
                <div
                  key={role.id}
                  className="relative flex min-h-9 items-center [&_label]:after:absolute [&_label]:after:inset-0"
                >
                  <CheckboxInput
                    label={role.name}
                    value={selected.has(role.id)}
                    onChange={(checked) => onToggle(role.id, checked)}
                  />
                </div>
              ))}
            </div>
          )
      )}
    </div>
  );
}

type Field = "username" | "email" | "policy";

/** A password the backend has just set, for the one-time display. */
type NewPassword = { password: string; email: string };

/** What a save sends that the one-time display names: the password (if any) and the e-mail. */
type Save = { password: string | null; email: string };

/** A set password, for `IssuedPasswordDialog`: a new account's, or a replaced one. */
export type IssuedPassword = NewPassword & { replaced: boolean };

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
  onDone,
  onPendingChange
}: {
  user?: AdminUser;
  onDone: (issued?: NewPassword) => void;
  /** The save is running: the dialog holds still until it has landed. */
  onPendingChange: (pending: boolean) => void;
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
  // Both come from what the save sent, not from the fields, which can change
  // while it runs.
  function finish({ password, email }: Save) {
    if (password) {
      onDone({ password, email });
    } else {
      void queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      onDone();
    }
  }

  const saveCallbacks = {
    onMutate: () => onPendingChange(true),
    onSettled: () => onPendingChange(false),
    onSuccess: (_data: unknown, save: Save) => finish(save),
    onError: (error: Error) => toastApiError(error, t)
  };

  const create = useMutation({
    mutationFn: ({ password, email }: Save & { password: string }) =>
      unwrap(
        browserApi.POST("/api/v1/admin/users/", {
          body: {
            email,
            username: username.trim() || null,
            password,
            roles: [...roleIds].map((id) => ({ id }))
          }
        })
      ),
    ...saveCallbacks
  });

  const updateUser = useMutation({
    mutationFn: ({ password, email }: Save) => {
      if (!user?.username) throw new Error("missing username");
      return unwrap(
        browserApi.POST("/api/v1/admin/users/{username}/", {
          params: { path: { username: user.username } },
          body: {
            email,
            // Sent only when changed: a new username signs the user out.
            username: username.trim() !== user.username ? username.trim() : undefined,
            password: password ?? undefined,
            roles: [...roleIds].map((id) => ({ id }))
          }
        })
      );
    },
    ...saveCallbacks
  });

  const pending = create.isPending || updateUser.isPending;
  const needsPassword = mode === "create" || replacePassword;
  const policyUnavailable = !policyQuery.isPending && policy === null;
  const errors: Record<Field, string | undefined> = {
    // A user without a username cannot be updated at all (see submit).
    username:
      (mode === "create" || user?.username) && !username.trim()
        ? t("admin_users_username_required")
        : undefined,
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
      revealProblems(() => setSubmitted(true), fields[first].current);
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
    if (mode === "update") updateUser.mutate({ password, email: email.trim() });
    else if (password) create.mutate({ password, email: email.trim() });
  }

  const usernameError = shown("username");
  const emailError = shown("email");

  return (
    // No close button while saving (Escape waits too, in the dialog): the
    // password the save sets must reach its one-time view.
    <DialogContent
      className={`max-h-[85vh] overflow-y-auto ${DIALOG_TOP_ON_TOUCH}`}
      showCloseButton={!pending}
    >
      <DialogHeader>
        <DialogTitle>{mode === "create" ? t("create_a_new_user") : t("edit_user")}</DialogTitle>
        <DialogDescription>
          {mode === "create" ? t("create_a_new_user") : t("edit_the_selected_user")}
        </DialogDescription>
      </DialogHeader>

      <form id={formId} className="flex flex-col gap-4" noValidate onSubmit={submit}>
        <FormLayout defaultOptionality="required" className="gap-4">
          <TextInput
            ref={usernameRef}
            label={t("username")}
            description={
              mode === "update"
                ? t("username_change_logout_hint")
                : t("unique_username_description")
            }
            value={username}
            onChange={setUsername}
            autoComplete="off"
            status={usernameError ? { type: "error", message: usernameError } : undefined}
          />
          <TextInput
            ref={emailRef}
            type="email"
            label={t("email")}
            value={email}
            onChange={setEmail}
            autoComplete="off"
            status={emailError ? { type: "error", message: emailError } : undefined}
          />
        </FormLayout>

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
          // A choice applied on save, so a checkbox: a switch acts at once.
          // The box sits on its label's line, not centred on the description;
          // the whole block is the target.
          <div className="relative [&_.astryx-checkbox-input>div]:items-start [&_label]:after:absolute [&_label]:after:inset-0">
            <CheckboxInput
              label={t("admin_password_replace")}
              description={t("admin_password_replace_desc") + oneTimeHint}
              value={replacePassword}
              onChange={setReplacePassword}
            />
          </div>
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
      </form>

      {/* Outside the form: its changes save on their own, and Enter in its
          search field must not submit the user. */}
      {user ? <UserGroupField user={user} isDisabled={pending} /> : null}

      <DialogFooter>
        <Button label={t("cancel")} isDisabled={pending} onClick={() => onDone()} />
        <Button
          type="submit"
          form={formId}
          variant="primary"
          label={mode === "create" ? t("create_user") : t("save_changes")}
          // Keeps focus while saving; a second press is ignored above.
          isLoading={pending}
          isInterruptible
        />
      </DialogFooter>
    </DialogContent>
  );
}

/**
 * Create or edit a user. Update targets POST /api/v1/admin/users/{username}/
 * with the current username; a changed one goes in the body. Editing also
 * assigns user groups, which save on their own as they change. While the
 * save runs the dialog cannot be closed (Cancel, Escape, close button), as in
 * the Svelte app. A password the save sets goes to `onIssued`, for an
 * `IssuedPasswordDialog` owned by the page: an edit dialog lives in its table
 * row, which a refetch may still drop mid-save (a renamed user under a
 * username filter), taking the dialog with it.
 */
export function UserEditorDialog({
  open,
  onOpenChange,
  user,
  onIssued
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Omitted → create mode. */
  user?: AdminUser;
  onIssued: (issued: IssuedPassword) => void;
}) {
  // The save only; a group change (it saves on its own) does not hold it.
  const [saving, setSaving] = useState(false);
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (next || !saving) onOpenChange(next);
      }}
    >
      {open && (
        <UserEditorForm
          user={user}
          onPendingChange={setSaving}
          onDone={(next) => {
            onOpenChange(false);
            if (next) onIssued({ ...next, replaced: user !== undefined });
          }}
        />
      )}
    </Dialog>
  );
}

/**
 * The one-time view of a password the user editor set. The users list is
 * invalidated only once it closes, but a background refetch (window focus,
 * a group change) can still change or drop rows while it is open, so the page
 * owns this view, never a table row.
 */
export function IssuedPasswordDialog({
  issued,
  onClose
}: {
  issued: IssuedPassword | null;
  onClose: () => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  return (
    <SecretRevealDialog
      title={issued?.replaced ? t("admin_password_replaced_title") : t("admin_user_created_title")}
      secret={issued?.password ?? null}
      warning={
        issued
          ? `${t("admin_issued_password_handover", { email: issued.email })} ${t("admin_password_one_time_hint")}`
          : undefined
      }
      copyFailedMessage={t("admin_issued_password_copy_failed")}
      onClose={() => {
        onClose();
        void queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      }}
    />
  );
}
