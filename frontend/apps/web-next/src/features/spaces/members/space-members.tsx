"use client";

import { Button as AstryxButton } from "@astryxdesign/core/Button";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2, UserPlus, Users } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { ConfirmDialog } from "@/components/composites/confirm-dialog";
import { FieldProblem, fieldProblemProps } from "@/components/composites/field-problem";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAppContext } from "@/components/providers/app-context";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger
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
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { toastApiError } from "@/lib/api/toast";
import { RemovalFocusScope, useRemovalMutation } from "@/features/spaces/removal";
import type { SpaceMember, SpaceRoleValue } from "@/features/spaces/space";
import { useSpace } from "@/features/spaces/use-space";
import { PageHeader } from "@/components/composites/page-header";

function useInvalidateSpace() {
  const { routeId } = useSpace();
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
}

function RoleSelect({
  value,
  roles,
  onChange,
  disabled
}: {
  value: SpaceRoleValue;
  roles: Schema<"SpaceRole">[];
  onChange: (role: SpaceRoleValue) => void;
  disabled?: boolean;
}) {
  const t = useTranslations();
  return (
    <Select
      value={value}
      disabled={disabled}
      onValueChange={(next) => onChange(next as SpaceRoleValue)}
    >
      <SelectTrigger size="sm" className="w-32" aria-label={t("role")}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {roles.map((role) => (
          <SelectItem key={role.value} value={role.value}>
            {role.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function MemberRow({ member }: { member: SpaceMember }) {
  const t = useTranslations();
  const { space, can } = useSpace();
  const { user } = useAppContext();
  const invalidate = useInvalidateSpace();
  const isSelf = member.id === user.id;

  const updateRole = useMutation({
    mutationFn: (role: SpaceRoleValue) =>
      unwrap(
        browserApi.PATCH("/api/v1/spaces/{id}/members/{user_id}/", {
          params: { path: { id: space.id, user_id: member.id } },
          body: { role }
        })
      ),
    onSuccess: invalidate,
    onError: (error) => toastApiError(error, t)
  });

  const removeMember = useRemovalMutation({
    mutationFn: () =>
      unwrap(
        browserApi.DELETE("/api/v1/spaces/{id}/members/{user_id}/", {
          params: { path: { id: space.id, user_id: member.id } }
        })
      ),
    refresh: invalidate
  });

  return (
    <div className="border-border flex items-center justify-between gap-4 border-b py-3">
      <span className="truncate text-sm">
        {member.email}
        {isSelf ? ` (${t("you")})` : ""}
      </span>
      {can("edit", "member") && !isSelf ? (
        <div className="flex items-center gap-1">
          <RoleSelect
            value={member.role}
            roles={space.available_roles}
            onChange={(role) => updateRole.mutate(role)}
            disabled={updateRole.isPending || removeMember.isPending}
          />
          <ConfirmDialog
            trigger={
              <Button variant="ghost" size="icon" aria-label={t("remove")}>
                <Trash2 className="text-destructive size-4" />
              </Button>
            }
            title={t("remove")}
            description={member.email}
            confirmLabel={t("confirm_deletion")}
            pending={removeMember.isPending}
            onConfirm={() => removeMember.mutateAsync().then(() => undefined)}
          />
        </div>
      ) : (
        <span className="text-muted-foreground text-sm capitalize">{member.role}</span>
      )}
    </div>
  );
}

/**
 * "Lägg till medlem": adds an existing user to the space. The members page
 * shows it as its primary action; `variant="header"` is the quieter button in
 * the space header on the other tabs (same name, same dialog).
 */
/** Adds a member: a user picked from the search, and a role. A missing pick shows on add. */
export function AddMemberDialog({ variant = "page" }: { variant?: "page" | "header" }) {
  const t = useTranslations();
  const roleId = useId();
  const { space } = useSpace();
  const invalidate = useInvalidateSpace();
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [role, setRole] = useState<SpaceRoleValue>(space.available_roles[0]?.value ?? "editor");
  const [submitted, setSubmitted] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);
  const userProblem = submitted && !selectedId ? t("form_problem_choose_user") : null;

  const memberIds = new Set(space.members.items.map((member) => member.id));
  const { data: candidates } = useQuery({
    queryKey: ["users", "search", filter],
    queryFn: async () => {
      const page = await unwrap(
        browserApi.GET("/api/v1/users/", {
          params: { query: { email: filter || null, limit: 10 } }
        })
      );
      return page.items;
    },
    enabled: open
  });

  const addMember = useMutation({
    mutationFn: (body: { id: string; role: SpaceRoleValue }) =>
      unwrap(
        browserApi.POST("/api/v1/spaces/{id}/members/", {
          params: { path: { id: space.id } },
          body
        })
      ),
    onSuccess: () => {
      invalidate();
      setOpen(false);
      setSelectedId(null);
      setFilter("");
    },
    onError: (error) => toastApiError(error, t)
  });

  const selectable = (candidates ?? []).filter((user) => !memberIds.has(user.id));

  function add() {
    if (addMember.isPending) return;
    if (!selectedId) {
      // Rendered before focus moves, so the field is read with its error.
      flushSync(() => setSubmitted(true));
      searchRef.current?.focus();
      return;
    }
    addMember.mutate({ id: selectedId, role });
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setSubmitted(false);
        setOpen(next);
      }}
    >
      <DialogTrigger asChild>
        {variant === "header" ? (
          <AstryxButton
            label={t("add_member")}
            variant="secondary"
            icon={<UserPlus aria-hidden="true" />}
          />
        ) : (
          <AstryxButton label={t("add_member")} variant="primary" />
        )}
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("add_member")}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="member-search">{t("email")}</Label>
            <Input
              ref={searchRef}
              id="member-search"
              value={filter}
              placeholder={t("member_search_placeholder")}
              onChange={(event) => {
                setFilter(event.target.value);
                setSelectedId(null);
              }}
              {...fieldProblemProps("member-search", userProblem)}
            />
            <FieldProblem id="member-search" problem={userProblem} />
            <div className="flex max-h-48 flex-col overflow-y-auto rounded-md border">
              {selectable.length === 0 ? (
                <p className="text-muted-foreground p-3 text-sm">{t("no_results")}</p>
              ) : (
                selectable.map((user) => (
                  <button
                    key={user.id}
                    type="button"
                    onClick={() => setSelectedId(user.id)}
                    aria-pressed={selectedId === user.id}
                    className={`hover:bg-muted px-3 py-2 text-left text-sm ${
                      selectedId === user.id ? "bg-muted font-medium" : ""
                    }`}
                  >
                    {user.email}
                  </button>
                ))
              )}
            </div>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor={roleId}>{t("role")}</Label>
            <Select value={role} onValueChange={(next) => setRole(next as SpaceRoleValue)}>
              <SelectTrigger id={roleId} className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {space.available_roles.map((availableRole) => (
                  <SelectItem key={availableRole.value} value={availableRole.value}>
                    {availableRole.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            {t("cancel")}
          </Button>
          {/* Never disabled: busy, it keeps focus and a second press is ignored. */}
          <Button aria-busy={addMember.isPending || undefined} onClick={add}>
            {addMember.isPending ? t("loading") : t("add_member")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function GroupMemberRow({ group }: { group: Schema<"SpaceGroupMember"> }) {
  const t = useTranslations();
  const { space, can } = useSpace();
  const invalidate = useInvalidateSpace();

  const updateRole = useMutation({
    mutationFn: (role: SpaceRoleValue) =>
      unwrap(
        browserApi.PATCH("/api/v1/spaces/{id}/group-members/{group_id}/", {
          params: { path: { id: space.id, group_id: group.id } },
          body: { role }
        })
      ),
    onSuccess: invalidate,
    onError: (error) => toastApiError(error, t)
  });

  const removeGroup = useRemovalMutation({
    mutationFn: () =>
      unwrap(
        browserApi.DELETE("/api/v1/spaces/{id}/group-members/{group_id}/", {
          params: { path: { id: space.id, group_id: group.id } }
        })
      ),
    refresh: invalidate
  });

  return (
    <div className="border-border flex items-center justify-between gap-4 border-b py-3">
      <span className="flex items-center gap-2 text-sm">
        <Users className="text-muted-foreground size-4" />
        <span className="font-medium">{group.name}</span>
        <span className="text-muted-foreground">
          {group.user_count} {group.user_count === 1 ? t("user") : t("users")}
        </span>
      </span>
      {can("edit", "group_member") ? (
        <div className="flex items-center gap-1">
          <RoleSelect
            value={group.role}
            roles={space.available_roles}
            onChange={(role) => updateRole.mutate(role)}
            disabled={updateRole.isPending || removeGroup.isPending}
          />
          <ConfirmDialog
            trigger={
              <Button variant="ghost" size="icon" aria-label={t("remove")}>
                <Trash2 className="text-destructive size-4" />
              </Button>
            }
            title={t("remove")}
            description={group.name}
            confirmLabel={t("confirm_deletion")}
            pending={removeGroup.isPending}
            onConfirm={() => removeGroup.mutateAsync().then(() => undefined)}
          />
        </div>
      ) : (
        <span className="text-muted-foreground text-sm capitalize">{group.role}</span>
      )}
    </div>
  );
}

/** Adds a user group with a role. A missing group shows on add. */
function AddGroupMemberDialog() {
  const t = useTranslations();
  const groupId = useId();
  const roleId = useId();
  const { space } = useSpace();
  const invalidate = useInvalidateSpace();
  const [open, setOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [role, setRole] = useState<SpaceRoleValue>(space.available_roles[0]?.value ?? "editor");
  const [submitted, setSubmitted] = useState(false);
  const groupRef = useRef<HTMLButtonElement>(null);
  const groupProblem = submitted && !selectedId ? t("form_problem_choose_user_group") : null;

  const groupMemberIds = new Set((space.group_members?.items ?? []).map((group) => group.id));
  const { data: groups } = useQuery({
    queryKey: ["user-groups"],
    queryFn: async () => {
      const result = await unwrap(browserApi.GET("/api/v1/user-groups/"));
      return result.items;
    },
    enabled: open
  });

  const addGroup = useMutation({
    mutationFn: (body: { id: string; role: SpaceRoleValue }) =>
      unwrap(
        browserApi.POST("/api/v1/spaces/{id}/group-members/", {
          params: { path: { id: space.id } },
          body
        })
      ),
    onSuccess: () => {
      invalidate();
      setOpen(false);
      setSelectedId(null);
    },
    onError: (error) => toastApiError(error, t)
  });

  const selectable = (groups ?? []).filter((group) => !groupMemberIds.has(group.id));

  function add() {
    if (addGroup.isPending) return;
    if (!selectedId) {
      // Rendered before focus moves, so the field is read with its error.
      flushSync(() => setSubmitted(true));
      groupRef.current?.focus();
      return;
    }
    addGroup.mutate({ id: selectedId, role });
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setSubmitted(false);
        setOpen(next);
      }}
    >
      <DialogTrigger asChild>
        <AstryxButton label={t("add_group")} variant="secondary" />
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("add_group")}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor={groupId}>{t("user_groups")}</Label>
            <Select value={selectedId ?? ""} onValueChange={setSelectedId}>
              <SelectTrigger
                ref={groupRef}
                id={groupId}
                className="w-full"
                {...fieldProblemProps(groupId, groupProblem)}
              >
                <SelectValue placeholder={t("user_groups")} />
              </SelectTrigger>
              <SelectContent>
                {selectable.map((group) => (
                  <SelectItem key={group.id} value={group.id}>
                    {group.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <FieldProblem id={groupId} problem={groupProblem} />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor={roleId}>{t("role")}</Label>
            <Select value={role} onValueChange={(next) => setRole(next as SpaceRoleValue)}>
              <SelectTrigger id={roleId} className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {space.available_roles.map((availableRole) => (
                  <SelectItem key={availableRole.value} value={availableRole.value}>
                    {availableRole.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            {t("cancel")}
          </Button>
          {/* Never disabled: busy, it keeps focus and a second press is ignored. */}
          <Button aria-busy={addGroup.isPending || undefined} onClick={add}>
            {addGroup.isPending ? t("loading") : t("add_group")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function SpaceMembers() {
  const t = useTranslations();
  const { space, can } = useSpace();
  const headingRef = useRef<HTMLHeadingElement>(null);

  const editors = space.members.items.filter(
    (member) => member.role === "admin" || member.role === "editor"
  );
  const viewers = space.members.items.filter((member) => member.role === "viewer");
  const viewerRoleAvailable = space.available_roles.some((role) => role.value === "viewer");
  const groupMembers = space.group_members?.items ?? [];

  return (
    // Removing a member or group takes its row (and remove button) away: focus goes to the title.
    <RemovalFocusScope target={headingRef}>
      <div className="flex w-full max-w-5xl flex-col gap-8">
        <PageHeader
          headingLevel={2}
          headingRef={headingRef}
          title={t("members")}
          actions={
            can("add", "group_member") || can("add", "member") ? (
              <>
                {can("add", "group_member") && <AddGroupMemberDialog />}
                {can("add", "member") && <AddMemberDialog />}
              </>
            ) : undefined
          }
        />

        <SettingsGroup title={t("current_members")}>
          <SettingsRow title={t("admins_editors")} description={t("admins_editors_description")}>
            <div className="flex flex-col">
              {editors.map((member) => (
                <MemberRow key={member.id} member={member} />
              ))}
            </div>
          </SettingsRow>
          {viewerRoleAvailable && (
            <SettingsRow title={t("viewers")} description={t("viewers_description")}>
              <div className="flex flex-col">
                {viewers.length === 0 ? (
                  <p className="text-muted-foreground py-3 text-sm">{t("no_viewers_in_space")}</p>
                ) : (
                  viewers.map((member) => <MemberRow key={member.id} member={member} />)
                )}
              </div>
            </SettingsRow>
          )}
        </SettingsGroup>

        <SettingsGroup title={t("group_members")}>
          <SettingsRow title={t("user_groups")} description={t("user_groups_description")}>
            <div className="flex flex-col">
              {groupMembers.length === 0 ? (
                <p className="text-muted-foreground py-3 text-sm">
                  {t("no_group_members_in_space")}
                </p>
              ) : (
                groupMembers.map((group) => <GroupMemberRow key={group.id} group={group} />)
              )}
            </div>
          </SettingsRow>
        </SettingsGroup>
      </div>
    </RemovalFocusScope>
  );
}
