"use client";

import { Avatar } from "@astryxdesign/core/Avatar";
import { BottomSheet } from "@astryxdesign/core/BottomSheet";
import { Button as AstryxButton } from "@astryxdesign/core/Button";
import { useCollator } from "@astryxdesign/core/i18n";
import { IconButton } from "@astryxdesign/core/IconButton";
import { List, ListItem } from "@astryxdesign/core/List";
import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronRight, Trash2, UserPlus, Users, X } from "lucide-react";
import { useTranslations } from "use-intl";
import { useId, useMemo, useRef, useState, type ReactNode } from "react";
import { ConfirmDialog, ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { DockedActions } from "@/components/shell/docked-actions";
import {
  FieldProblem,
  fieldProblemProps,
  revealProblems
} from "@/components/composites/field-problem";
import type { SearchableItem, SearchSource } from "@astryxdesign/core/Typeahead";
import { Typeahead } from "@/components/astryx/typeahead";
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
import { SEARCH_DEBOUNCE_MS } from "@/lib/hooks/use-debounced-value";
import { userGroupsQueryOptions } from "@/features/admin/user-groups/user-groups";
import { PHONE_QUERY, useMediaMatch } from "@/lib/hooks/use-media-match";
import { toast } from "@/lib/toast";
import { RemovalFocusScope, useRemovalMutation } from "@/features/spaces/removal";
import type { SpaceMember, SpaceRoleValue } from "@/features/spaces/space";
import { useSpace } from "@/features/spaces/use-space";
import { PageHeader } from "@/components/composites/page-header";
import {
  personToneClass,
  SPACE_ROLE_DESCRIPTION_KEYS,
  SPACE_ROLE_LABEL_KEYS,
  sortMembersByRole
} from "./member-avatar";

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
            {t(SPACE_ROLE_LABEL_KEYS[role.value])}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

type GroupMember = Schema<"SpaceGroupMember">;

/** A user or a user group in the space. */
type Membership = { kind: "member"; member: SpaceMember } | { kind: "group"; group: GroupMember };

/** Changing a membership's role and removing it from the space. */
function useMembership(membership: Membership) {
  const t = useTranslations();
  const { space } = useSpace();
  const invalidate = useInvalidateSpace();

  const updateRole = useMutation({
    mutationFn: async (role: SpaceRoleValue) => {
      if (membership.kind === "member") {
        await unwrap(
          browserApi.PATCH("/api/v1/spaces/{id}/members/{user_id}/", {
            params: { path: { id: space.id, user_id: membership.member.id } },
            body: { role }
          })
        );
      } else {
        await unwrap(
          browserApi.PATCH("/api/v1/spaces/{id}/group-members/{group_id}/", {
            params: { path: { id: space.id, group_id: membership.group.id } },
            body: { role }
          })
        );
      }
    },
    onSuccess: invalidate,
    onError: (error) => toastApiError(error, t)
  });

  const remove = useRemovalMutation({
    mutationFn: async () => {
      if (membership.kind === "member") {
        await unwrap(
          browserApi.DELETE("/api/v1/spaces/{id}/members/{user_id}/", {
            params: { path: { id: space.id, user_id: membership.member.id } }
          })
        );
      } else {
        await unwrap(
          browserApi.DELETE("/api/v1/spaces/{id}/group-members/{group_id}/", {
            params: { path: { id: space.id, group_id: membership.group.id } }
          })
        );
      }
    },
    refresh: invalidate
  });

  return { updateRole, remove };
}

function MemberRow({ member }: { member: SpaceMember }) {
  const t = useTranslations();
  const { space, can } = useSpace();
  const { user } = useAppContext();
  const isSelf = member.id === user.id;
  const { updateRole, remove: removeMember } = useMembership({ kind: "member", member });

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
        <span className="text-muted-foreground text-sm">
          {t(SPACE_ROLE_LABEL_KEYS[member.role])}
        </span>
      )}
    </div>
  );
}

/** Users to add as members: those whose email matches, or the first ones without a search. */
function memberCandidatesQueryOptions(email: string | null) {
  return queryOptions({
    queryKey: ["users", "search", email],
    queryFn: async () => {
      const page = await unwrap(
        browserApi.GET("/api/v1/users/", { params: { query: { email, limit: 10 } } })
      );
      return page.items;
    }
  });
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
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<SearchableItem | null>(null);
  const [role, setRole] = useState<SpaceRoleValue>(space.available_roles[0]?.value ?? "editor");
  const [submitted, setSubmitted] = useState(false);
  const searchRef = useRef<HTMLDivElement>(null);
  const userProblem = submitted && !selected ? t("form_problem_choose_user") : null;

  // Users who are not members yet: the first ones on focus, then those matching
  // the typed email once typing pauses (any length, as the Svelte app).
  const members = space.members.items;
  const candidates = useMemo<SearchSource<SearchableItem>>(() => {
    const memberIds = new Set(members.map((member) => member.id));
    const load = async (email: string | null) => {
      const users = await queryClient.query(memberCandidatesQueryOptions(email));
      return users
        .filter((user) => !memberIds.has(user.id))
        .map((user) => ({ id: user.id, label: user.email }));
    };
    return {
      search: (query) => load(query.trim() || null),
      bootstrap: () => load(null)
    };
  }, [members, queryClient]);

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
      setSelected(null);
    },
    onError: (error) => toastApiError(error, t)
  });

  function add() {
    if (addMember.isPending) return;
    if (!selected) {
      revealProblems(() => setSubmitted(true), searchRef.current?.querySelector("input"));
      return;
    }
    addMember.mutate({ id: selected.id, role });
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
          <Typeahead
            ref={searchRef}
            label={t("email")}
            placeholder={t("member_search_placeholder")}
            searchSource={candidates}
            value={selected}
            onChange={setSelected}
            hasEntriesOnFocus
            debounceMs={SEARCH_DEBOUNCE_MS}
            emptySearchResultsText={t("no_results")}
            status={userProblem ? { type: "error", message: userProblem } : undefined}
            width="100%"
          />
          <div className="flex flex-col gap-2">
            <Label htmlFor={roleId}>{t("role")}</Label>
            <Select value={role} onValueChange={(next) => setRole(next as SpaceRoleValue)}>
              <SelectTrigger id={roleId} className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {space.available_roles.map((availableRole) => (
                  <SelectItem key={availableRole.value} value={availableRole.value}>
                    {t(SPACE_ROLE_LABEL_KEYS[availableRole.value])}
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

function GroupMemberRow({ group }: { group: GroupMember }) {
  const t = useTranslations();
  const { space, can } = useSpace();
  const { updateRole, remove: removeGroup } = useMembership({ kind: "group", group });

  return (
    <div className="border-border flex items-center justify-between gap-4 border-b py-3">
      <span className="flex items-center gap-2 text-sm">
        <Users className="text-muted-foreground size-4" />
        <span className="font-medium">{group.name}</span>
        <span className="text-muted-foreground">
          {t("space_group_user_count", { count: group.user_count ?? 0 })}
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
        <span className="text-muted-foreground text-sm">
          {t(SPACE_ROLE_LABEL_KEYS[group.role])}
        </span>
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
  const { data: groups } = useQuery({ ...userGroupsQueryOptions(browserApi), enabled: open });

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
      revealProblems(() => setSubmitted(true), groupRef.current);
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
                    {t(SPACE_ROLE_LABEL_KEYS[availableRole.value])}
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

/** The name, the line under it and the role a phone row and the role sheet show. */
function useMembershipLabels(membership: Membership) {
  const t = useTranslations();
  if (membership.kind === "member") {
    const { member } = membership;
    // The API has no display name: a username names the row when there is one.
    const username = member.username?.trim();
    return {
      key: `member-${member.id}`,
      name: username || member.email,
      detail: username && username !== member.email ? member.email : null,
      role: member.role
    };
  }
  const { group } = membership;
  return {
    key: `group-${group.id}`,
    name: group.name,
    detail: t("space_group_user_count", { count: group.user_count ?? 0 }),
    role: group.role
  };
}

/**
 * A member or group as a phone row (decision 25): avatar, name, the e-mail or
 * user count, and the role in words at the end. Tapping it opens the role
 * sheet; your own row, or one you may not change, only reads. Where the rows
 * are narrow for their text (larger text sizes, 18rem of the rows'
 * container), the role moves under the name instead, so the name keeps room.
 */
function PhoneMembershipRow({
  membership,
  onOpen
}: {
  membership: Membership;
  onOpen: (() => void) | null;
}) {
  const t = useTranslations();
  const { user } = useAppContext();
  const { key, name, detail, role } = useMembershipLabels(membership);
  const isSelf = membership.kind === "member" && membership.member.id === user.id;
  const roleLabel = t(SPACE_ROLE_LABEL_KEYS[role]);
  return (
    <ListItem
      data-membership={key}
      label={
        <span className="block font-semibold break-words">
          {name}
          {isSelf ? ` (${t("you")})` : ""}
        </span>
      }
      description={
        <>
          {detail ? <span className="block [overflow-wrap:anywhere]">{detail}</span> : null}
          {/* Under the name where the rows are narrow; for screen readers always. */}
          <span className="block @min-[18rem]/rows:sr-only">{`${t("role")}: ${roleLabel}`}</span>
        </>
      }
      startContent={
        membership.kind === "member" ? (
          <Avatar
            name={name}
            size="md"
            tooltip={false}
            className={personToneClass(membership.member.id)}
            aria-hidden="true"
          />
        ) : (
          <span
            aria-hidden="true"
            className="bg-ax-muted text-ax-text-secondary flex size-9 shrink-0 items-center justify-center rounded-full"
          >
            <Users className="size-4" />
          </span>
        )
      }
      endContent={
        <span aria-hidden="true" className="text-ax-text-secondary flex items-center gap-1">
          <span className="hidden @min-[18rem]/rows:inline">{roleLabel}</span>
          {/* The chevron's place stays, so roles line up with rows that have one. */}
          {onOpen ? <ChevronRight className="size-4" /> : <span className="size-4" />}
        </span>
      }
      onClick={onOpen ?? undefined}
    />
  );
}

/** A role's rows under its heading and count (the list says its own count). */
function MembershipSection({
  title,
  count,
  children
}: {
  title: string;
  count: number;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="flex flex-col">
      <h3 className="flex min-h-11 items-center justify-between gap-3 font-semibold">
        <span id={id}>{title}</span>
        <span
          aria-hidden="true"
          className="text-ax-text-secondary text-sm font-normal tabular-nums"
        >
          {count}
        </span>
      </h3>
      <div className="@container/rows">
        <List hasDividers edgeCompensation="inline" aria-labelledby={id}>
          {children}
        </List>
      </div>
    </section>
  );
}

/**
 * A member's or group's role sheet (decision 25): the roles to pick from and
 * "Ta bort från ytan" behind a confirmation. A role applies when it is picked
 * (tap, Enter or Space), so the roles are buttons, not radios: moving through
 * radios with the arrow keys would pick each one on the way (WCAG 3.2.2).
 * While a pick saves, the others wait. Focus goes back to the row, wherever
 * a new role put it (WCAG 2.4.3). Kept mounted while it closes, so it slides
 * away and leaves the dialog stack.
 */
function RoleSheet({
  membership,
  isOpen,
  onClose
}: {
  membership: Membership;
  isOpen: boolean;
  onClose: () => void;
}) {
  const t = useTranslations();
  const { space } = useSpace();
  const { key, name, detail, role } = useMembershipLabels(membership);
  const { updateRole, remove } = useMembership(membership);
  const [confirming, setConfirming] = useState(false);
  const [picked, setPicked] = useState<SpaceRoleValue | null>(null);
  const current = picked ?? role;

  function close() {
    onClose();
    requestAnimationFrame(() =>
      document.querySelector<HTMLElement>(`[data-membership="${key}"] button`)?.focus()
    );
  }

  function pick(next: SpaceRoleValue) {
    if (updateRole.isPending) return;
    if (next === role) return close();
    setPicked(next);
    updateRole.mutate(next, {
      onSuccess: () => {
        toast.success(t("role_changed"));
        close();
      },
      onSettled: () => setPicked(null)
    });
  }

  return (
    <>
      <BottomSheet
        isOpen={isOpen && !confirming}
        onOpenChange={(open) => {
          if (!open) close();
        }}
        label={name}
        height="hug"
      >
        <div className="flex items-start gap-2 ps-4 pe-2 pt-4">
          <h2 className="min-w-0 flex-1 pt-2 text-lg font-semibold text-balance break-words">
            {name}
          </h2>
          <IconButton
            label={t("close")}
            icon={<X className="size-5" />}
            variant="ghost"
            onClick={close}
          />
        </div>
        <div className="flex flex-col gap-5 px-4 pt-1 pb-[calc(1rem+env(safe-area-inset-bottom,0px))]">
          {detail ? (
            <p className="text-ax-text-secondary [overflow-wrap:anywhere]">{detail}</p>
          ) : null}
          <List
            header={t("role")}
            hasDividers
            edgeCompensation="inline"
            aria-busy={updateRole.isPending || undefined}
          >
            {space.available_roles.map((available) => {
              const selected = available.value === current;
              return (
                <ListItem
                  key={available.value}
                  isSelected={selected}
                  onClick={() => pick(available.value)}
                  label={
                    <span className="block">
                      {t(SPACE_ROLE_LABEL_KEYS[available.value])}
                      {selected ? (
                        <span className="sr-only">{`, ${t("space_role_current")}`}</span>
                      ) : null}
                    </span>
                  }
                  description={t(SPACE_ROLE_DESCRIPTION_KEYS[available.value])}
                  endContent={
                    selected ? (
                      <Check aria-hidden="true" className="text-ax-text-accent size-5" />
                    ) : (
                      <span className="size-5" />
                    )
                  }
                />
              );
            })}
          </List>
          <div className="border-ax-border border-t pt-4">
            <AstryxButton
              variant="destructive"
              size="lg"
              width="100%"
              label={t("space_remove_from_space")}
              icon={<Trash2 aria-hidden="true" />}
              onClick={() => setConfirming(true)}
            />
          </div>
        </div>
      </BottomSheet>
      {/* Cancelling goes back to the sheet; removing ends with focus where
          RemovalFocusScope puts it. */}
      <ConfirmDialogControlled
        open={confirming}
        onOpenChange={(open) => {
          if (!open) setConfirming(false);
        }}
        title={membership.kind === "member" ? t("remove_member") : t("remove_group")}
        description={
          membership.kind === "member"
            ? t("confirm_remove_member", { memberEmail: membership.member.email })
            : t("confirm_remove_group", { groupName: membership.group.name })
        }
        confirmLabel={t("remove")}
        pending={remove.isPending}
        onConfirm={() =>
          remove.mutate(undefined, {
            onSuccess: () => {
              toast.success(t("member_removed"));
              setConfirming(false);
              onClose();
            }
          })
        }
      />
    </>
  );
}

/** Members and groups on a phone: rows by role, a role sheet on tap. */
function PhoneMembers() {
  const t = useTranslations();
  const { space, can } = useSpace();
  const { user } = useAppContext();
  const collator = useCollator();
  // The last sheet opened stays mounted while it closes.
  const [sheet, setSheet] = useState<{ membership: Membership; isOpen: boolean } | null>(null);

  const members = sortMembersByRole(space.members.items, collator.compare);
  const editors = members.filter((member) => member.role !== "viewer");
  const viewers = members.filter((member) => member.role === "viewer");
  const groups = space.group_members?.items ?? [];
  const opener = (membership: Membership) => {
    const editable =
      membership.kind === "member"
        ? can("edit", "member") && membership.member.id !== user.id
        : can("edit", "group_member");
    return editable ? () => setSheet({ membership, isOpen: true }) : null;
  };
  const rows = (memberships: Membership[]) =>
    memberships.map((membership) => (
      <PhoneMembershipRow
        key={membership.kind === "member" ? membership.member.id : membership.group.id}
        membership={membership}
        onOpen={opener(membership)}
      />
    ));

  return (
    <div className="flex flex-col gap-4">
      {editors.length > 0 ? (
        <MembershipSection title={t("admins_editors")} count={editors.length}>
          {rows(editors.map((member) => ({ kind: "member", member })))}
        </MembershipSection>
      ) : null}
      {viewers.length > 0 ? (
        <MembershipSection title={t("viewers")} count={viewers.length}>
          {rows(viewers.map((member) => ({ kind: "member", member })))}
        </MembershipSection>
      ) : null}
      {groups.length > 0 ? (
        <MembershipSection title={t("group_members")} count={groups.length}>
          {rows(groups.map((group) => ({ kind: "group", group })))}
        </MembershipSection>
      ) : null}
      {sheet ? (
        <RoleSheet
          key={
            sheet.membership.kind === "member"
              ? sheet.membership.member.id
              : sheet.membership.group.id
          }
          membership={sheet.membership}
          isOpen={sheet.isOpen}
          onClose={() => setSheet((current) => current && { ...current, isOpen: false })}
        />
      ) : null}
    </div>
  );
}

export function SpaceMembers() {
  const t = useTranslations();
  const { space, can } = useSpace();
  const phone = useMediaMatch(PHONE_QUERY);
  const headingRef = useRef<HTMLHeadingElement>(null);

  const editors = space.members.items.filter(
    (member) => member.role === "admin" || member.role === "editor"
  );
  const viewers = space.members.items.filter((member) => member.role === "viewer");
  const viewerRoleAvailable = space.available_roles.some((role) => role.value === "viewer");
  const groupMembers = space.group_members?.items ?? [];
  const canAdd = can("add", "group_member") || can("add", "member");

  return (
    // Removing a member or group takes its row (and remove button) away: focus goes to the title.
    <RemovalFocusScope target={headingRef}>
      <div className="flex w-full flex-col gap-8 max-md:gap-4">
        <PageHeader
          headingLevel={2}
          headingRef={headingRef}
          title={t("members")}
          actions={
            canAdd ? (
              // Docked at the bottom on a phone.
              <DockedActions label={t("space_members_actions")}>
                {can("add", "group_member") && <AddGroupMemberDialog />}
                {can("add", "member") && <AddMemberDialog />}
              </DockedActions>
            ) : undefined
          }
        />

        {phone !== false ? (
          <div className="md:hidden">
            <PhoneMembers />
          </div>
        ) : null}
        {phone !== true ? (
          <div className="flex flex-col gap-8 max-md:hidden">
            <SettingsGroup title={t("current_members")}>
              <SettingsRow
                title={t("admins_editors")}
                description={t("admins_editors_description")}
              >
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
                      <p className="text-muted-foreground py-3 text-sm">
                        {t("no_viewers_in_space")}
                      </p>
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
        ) : null}
      </div>
    </RemovalFocusScope>
  );
}
