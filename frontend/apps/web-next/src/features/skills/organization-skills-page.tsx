"use client";

import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpenCheck, Plus, Search, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useId, useState, type SubmitEvent } from "react";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "@/components/ui/alert-dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageHeader } from "@/components/composites/page-header";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError, getErrorMessage, unwrap } from "@/lib/api/errors";
import {
  isSkillInUse,
  ORGANIZATION_SKILLS_KEY,
  removalBlocked,
  removalRequest,
  selectedSkills,
  serverBlockingIds,
  SKILL_SELECTION_LIMIT,
  type OrganizationSkill,
  type SkillRemovalResult,
  type SkillUsage
} from "./organization-skills";

const LIST_PATH = "/spaces/organization/skills";

function useUsageLabel() {
  const t = useTranslations();
  return (usage: SkillUsage) => {
    if (!isSkillInUse(usage)) return null;
    return [
      t(
        usage.assistant_count === 1
          ? "organization_skills_usage_assistants"
          : "organization_skills_usage_assistants_plural",
        { count: String(usage.assistant_count) }
      ),
      t(
        usage.app_count === 1
          ? "organization_skills_usage_apps"
          : "organization_skills_usage_apps_plural",
        { count: String(usage.app_count) }
      ),
      t(
        usage.distinct_space_count === 1
          ? "organization_skills_usage_spaces"
          : "organization_skills_usage_spaces_plural",
        { count: String(usage.distinct_space_count) }
      )
    ].join(" · ");
  };
}

function resultMessage(result: SkillRemovalResult, t: ReturnType<typeof useTranslations>): string {
  const count = String(result.removed_ids.length);
  const base =
    result.detached.assistant_count > 0 || result.detached.app_count > 0
      ? t("organization_skills_removed_detached_success", {
          count,
          assistants: String(result.detached.assistant_count),
          apps: String(result.detached.app_count)
        })
      : t("organization_skills_removed_success", { count });
  return result.detached.personal_chat_count > 0
    ? `${base} ${t("organization_skills_removed_personal_chat_updated")}`
    : base;
}

export function OrganizationSkillsPage() {
  const t = useTranslations();
  const locale = useLocale();
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const search = searchParams.get("search")?.trim() ?? "";
  const removed = searchParams.get("removed") === "true";
  const [searchInput, setSearchInput] = useState(search);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [removalTargets, setRemovalTargets] = useState<OrganizationSkill[]>([]);
  const [announcement, setAnnouncement] = useState("");
  const usageLabel = useUsageLabel();
  const headingId = useId();

  const skills = useInfiniteQuery({
    queryKey: [...ORGANIZATION_SKILLS_KEY, search, removed],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      unwrap(
        browserApi.GET("/api/v1/skills/organization/", {
          params: { query: { cursor: pageParam, search: search || undefined, removed } }
        })
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    retry: false
  });
  const items = skills.data?.pages.flatMap((page) => page.items) ?? [];
  const chosen = selectedSkills(items, selectedIds);
  const selectable = items.slice(0, SKILL_SELECTION_LIMIT);
  const allSelected =
    selectable.length > 0 && selectable.every((item) => selectedIds.includes(item.id));

  function navigate(nextSearch: string, nextRemoved: boolean) {
    setSelectedIds([]);
    setRemovalTargets([]);
    const params = new URLSearchParams();
    if (nextSearch) params.set("search", nextSearch);
    if (nextRemoved) params.set("removed", "true");
    router.push(`${LIST_PATH}${params.size ? `?${params}` : ""}`);
  }

  function submitSearch(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    navigate(searchInput.trim(), removed);
  }

  function select(id: string, checked: boolean) {
    setSelectedIds((current) =>
      checked
        ? [...new Set([...current, id])].slice(0, SKILL_SELECTION_LIMIT)
        : current.filter((item) => item !== id)
    );
  }

  async function removedSkills(result: SkillRemovalResult) {
    setRemovalTargets([]);
    setSelectedIds([]);
    setAnnouncement(resultMessage(result, t));
    await queryClient.invalidateQueries({ queryKey: ORGANIZATION_SKILLS_KEY });
  }

  function statusLabel(skill: OrganizationSkill) {
    if (skill.removed_at) return t("organization_skills_removed_status");
    if (skill.execution_blocked) return t("organization_skills_status_blocked");
    return t(`organization_skills_status_${skill.publication_state}`);
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 pb-16">
      {/* A tab of the organization space: the space header holds the h1. */}
      <PageHeader
        headingLevel={2}
        headingId={headingId}
        title={t("skills")}
        actions={
          removed ? undefined : (
            <Button asChild>
              <Link href={`${LIST_PATH}/new`}>
                <Plus className="size-4" />
                {t("skills_library_create")}
              </Link>
            </Button>
          )
        }
      />
      <p className="text-muted-foreground max-w-3xl text-sm">
        {t("organization_skills_manage_intro")}
      </p>
      <nav className="flex gap-2" aria-label={t("organization_skills_filter_label")}>
        <Button
          variant={removed ? "ghost" : "secondary"}
          aria-current={!removed ? "page" : undefined}
          onClick={() => navigate(search, false)}
        >
          {t("organization_skills_current_filter")}
        </Button>
        <Button
          variant={removed ? "secondary" : "ghost"}
          aria-current={removed ? "page" : undefined}
          onClick={() => navigate(search, true)}
        >
          {t("organization_skills_removed_filter")}
        </Button>
      </nav>
      {removed && (
        <p className="text-muted-foreground text-sm">
          {t("organization_skills_removed_description")}
        </p>
      )}
      <p className={announcement ? "text-sm" : "sr-only"} role="status">
        {announcement}
      </p>
      <form onSubmit={submitSearch} role="search" className="flex max-w-xl gap-2">
        <div className="relative min-w-0 flex-1">
          <Search className="text-muted-foreground absolute top-1/2 left-3 size-4 -translate-y-1/2" />
          <Input
            type="search"
            maxLength={200}
            className="pl-9"
            value={searchInput}
            aria-label={t("skills_library_search_placeholder")}
            placeholder={t("skills_library_search_placeholder")}
            onChange={(event) => setSearchInput(event.target.value)}
          />
        </div>
        <Button type="submit" variant="outline">
          {t("search")}
        </Button>
        {search && (
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              setSearchInput("");
              navigate("", removed);
            }}
          >
            {t("clear")}
          </Button>
        )}
      </form>
      {skills.isPending ? (
        <p role="status" className="text-muted-foreground text-sm">
          {t("loading")}
        </p>
      ) : skills.isError && !skills.data ? (
        <Alert variant="destructive" role="alert">
          <AlertTitle>{t("request_failed")}</AlertTitle>
          <AlertDescription>
            <Button variant="outline" size="sm" onClick={() => void skills.refetch()}>
              {t("retry")}
            </Button>
          </AlertDescription>
        </Alert>
      ) : items.length === 0 ? (
        <div className="flex max-w-3xl flex-col items-center gap-3 rounded-xl border border-dashed p-10 text-center">
          <BookOpenCheck className="text-muted-foreground size-9" />
          {/* Under the tab's h2. */}
          <h3 className="font-medium">
            {removed && !search
              ? t("organization_skills_removed_empty")
              : search
                ? t("skills_library_no_results")
                : t("organization_skills_empty_manage_title")}
          </h3>
          {!removed && !search && (
            <>
              <p className="text-muted-foreground text-sm">
                {t("organization_skills_empty_manage_description")}
              </p>
              <Button asChild>
                <Link href={`${LIST_PATH}/new`}>{t("skills_library_create_first")}</Link>
              </Button>
            </>
          )}
        </div>
      ) : (
        <>
          {!removed && (
            <div className="flex flex-wrap items-center gap-3">
              <p className="text-muted-foreground text-sm" aria-live="polite">
                {t("organization_skills_selection_count", {
                  count: String(selectedIds.length),
                  limit: String(SKILL_SELECTION_LIMIT)
                })}
              </p>
              {chosen.length > 0 && (
                <>
                  <Button variant="outline" size="sm" onClick={() => setRemovalTargets(chosen)}>
                    <Trash2 className="size-4" />
                    {t("organization_skills_remove_selected")}
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => setSelectedIds([])}>
                    {t("clear")}
                  </Button>
                </>
              )}
            </div>
          )}
          <div className="overflow-x-auto rounded-xl border">
            <table className="w-full min-w-[700px] text-sm" aria-labelledby={headingId}>
              <thead>
                <tr className="border-b text-left">
                  {!removed && (
                    <th className="w-12 p-3">
                      <input
                        type="checkbox"
                        className="accent-primary size-4"
                        aria-label={t("organization_skills_select_shown", {
                          count: String(selectable.length)
                        })}
                        checked={allSelected}
                        onChange={(event) =>
                          setSelectedIds(
                            event.target.checked ? selectable.map((item) => item.id) : []
                          )
                        }
                      />
                    </th>
                  )}
                  <th className="p-3">{t("name")}</th>
                  <th className="p-3">{t("description")}</th>
                  <th className="p-3">{t("status")}</th>
                  <th className="p-3">{t("skills_library_revision_column")}</th>
                  <th className="p-3">{t("skills_library_updated_column")}</th>
                  {!removed && (
                    <th className="p-3">
                      <span className="sr-only">{t("actions")}</span>
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {items.map((skill) => (
                  <tr key={skill.id} className="border-b align-top last:border-0">
                    {!removed && (
                      <td className="p-3">
                        <input
                          type="checkbox"
                          className="accent-primary size-4"
                          aria-label={t("organization_skills_select_skill", {
                            name: skill.display_name
                          })}
                          checked={selectedIds.includes(skill.id)}
                          disabled={
                            selectedIds.length >= SKILL_SELECTION_LIMIT &&
                            !selectedIds.includes(skill.id)
                          }
                          onChange={(event) => select(skill.id, event.target.checked)}
                        />
                      </td>
                    )}
                    <td className="min-w-48 p-3">
                      <Link
                        className="font-medium underline-offset-2 hover:underline"
                        href={`${LIST_PATH}/${skill.id}`}
                      >
                        {skill.display_name}
                      </Link>
                      <p className="text-muted-foreground text-xs break-all">{skill.slug}</p>
                      {!removed && (
                        <p className="text-muted-foreground mt-2 text-xs">
                          {usageLabel(skill.usage) ?? t("organization_skills_usage_none")}
                          {skill.usage.personal_chat_pinned &&
                            ` · ${t("organization_skills_usage_personal_chat")}`}
                        </p>
                      )}
                    </td>
                    <td className="text-muted-foreground max-w-md p-3">{skill.description}</td>
                    <td className="p-3">
                      <Badge
                        variant={
                          skill.publication_state === "published" && !skill.execution_blocked
                            ? "secondary"
                            : "outline"
                        }
                      >
                        {statusLabel(skill)}
                      </Badge>
                    </td>
                    <td className="p-3 tabular-nums">
                      {t("organization_skills_version", {
                        version: String(skill.current_revision_number)
                      })}
                    </td>
                    <td className="p-3 tabular-nums">
                      {new Date(skill.updated_at).toLocaleString(locale, {
                        dateStyle: "short",
                        timeStyle: "short"
                      })}
                    </td>
                    {!removed && (
                      <td className="p-3">
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={t("organization_skills_remove_aria", {
                            name: skill.display_name
                          })}
                          onClick={() => setRemovalTargets([skill])}
                        >
                          <Trash2 className="size-4" />
                        </Button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {skills.hasNextPage && (
            <div className="flex justify-center">
              <Button
                variant="outline"
                disabled={skills.isFetchingNextPage}
                onClick={() => void skills.fetchNextPage()}
              >
                {skills.isFetchingNextPage ? t("loading") : t("load_more")}
              </Button>
            </div>
          )}
          {skills.isFetchNextPageError && (
            <Alert variant="destructive" role="alert">
              <AlertTitle>{t("organization_skills_load_more_error")}</AlertTitle>
              <AlertDescription>
                <Button variant="outline" size="sm" onClick={() => void skills.fetchNextPage()}>
                  {t("retry")}
                </Button>
              </AlertDescription>
            </Alert>
          )}
        </>
      )}
      {removalTargets.length > 0 && (
        <SkillRemovalDialog
          key={removalTargets.map((skill) => skill.id).join(",")}
          skills={removalTargets}
          onClose={() => setRemovalTargets([])}
          onRemoved={removedSkills}
          onExclude={(ids) => {
            setSelectedIds((current) => current.filter((id) => !ids.includes(id)));
            setRemovalTargets((current) => current.filter((skill) => !ids.includes(skill.id)));
          }}
        />
      )}
    </div>
  );
}

export function SkillRemovalDialog({
  skills,
  onClose,
  onRemoved,
  onExclude
}: {
  skills: OrganizationSkill[];
  onClose: () => void;
  onRemoved: (result: SkillRemovalResult) => Promise<void>;
  onExclude: (ids: string[]) => void;
}) {
  const t = useTranslations();
  const usageLabel = useUsageLabel();
  const [busy, setBusy] = useState(false);
  const [detachBindings, setDetachBindings] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [serverBlocked, setServerBlocked] = useState<string[]>([]);
  const blockers = skills.filter(
    (skill) => removalBlocked(skill.usage) || serverBlocked.includes(skill.id)
  );
  const request = removalRequest(skills, detachBindings, serverBlocked);

  async function remove() {
    if (busy || !request) return;
    setBusy(true);
    setError(null);
    try {
      const result = await unwrap(
        browserApi.POST("/api/v1/skills/organization/remove/", { body: request })
      );
      await onRemoved(result);
    } catch (cause) {
      setError(getErrorMessage(cause, t));
      if (cause instanceof EneoApiError && cause.code === 9051)
        setServerBlocked(serverBlockingIds(cause.details));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AlertDialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) onClose();
      }}
    >
      <AlertDialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto">
        <AlertDialogHeader>
          <AlertDialogTitle>
            {skills.length === 1
              ? t("organization_skills_remove_single_title")
              : t("organization_skills_remove_title", { count: String(skills.length) })}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {t("organization_skills_remove_description")}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <ul className="max-h-64 divide-y overflow-y-auto">
          {skills.map((skill) => (
            <li key={skill.id} className="py-3">
              <div className="flex flex-wrap items-center gap-2">
                <Link
                  className="text-sm font-medium underline"
                  href={`${LIST_PATH}/${skill.id}#organization-skill-adoption-heading`}
                  onClick={(event) => {
                    if (busy) event.preventDefault();
                    else onClose();
                  }}
                >
                  {skill.display_name}
                </Link>
                {blockers.includes(skill) && (
                  <Badge variant="outline">{t("organization_skills_usage_in_use")}</Badge>
                )}
              </div>
              <p className="text-muted-foreground text-sm">
                {usageLabel(skill.usage) ?? t("organization_skills_usage_none")}
              </p>
              {serverBlocked.includes(skill.id) && (
                <p className="text-destructive text-sm">
                  {t("organization_skills_remove_new_binding")}
                </p>
              )}
            </li>
          ))}
        </ul>
        {blockers.length > 0 && (
          <Alert>
            <AlertTitle>
              {t(
                skills.length === 1
                  ? "organization_skills_remove_blocked_single_title"
                  : "organization_skills_remove_blocked_title"
              )}
            </AlertTitle>
            <AlertDescription>
              <p>
                {t(
                  skills.length === 1
                    ? "organization_skills_remove_blocked_single_description"
                    : "organization_skills_remove_blocked_description"
                )}
              </p>
              <label className="mt-3 flex items-start gap-2">
                <input
                  type="checkbox"
                  className="accent-primary mt-1 size-4"
                  checked={detachBindings}
                  disabled={busy}
                  onChange={(event) => setDetachBindings(event.target.checked)}
                />
                <span>
                  <span className="block text-sm font-medium">
                    {t("organization_skills_remove_detach_label")}
                  </span>
                  <span className="text-muted-foreground text-xs">
                    {t("organization_skills_remove_detach_description")}
                  </span>
                </span>
              </label>
              {!detachBindings && blockers.length < skills.length && (
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-3"
                  onClick={() => onExclude(blockers.map((skill) => skill.id))}
                >
                  {t("organization_skills_remove_exclude_blocked", {
                    count: String(blockers.length)
                  })}
                </Button>
              )}
            </AlertDescription>
          </Alert>
        )}
        {error && (
          <Alert variant="destructive" role="alert">
            <AlertTitle>{t("organization_skills_remove_error")}</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>{t("cancel")}</AlertDialogCancel>
          <Button variant="destructive" disabled={busy || !request} onClick={() => void remove()}>
            {busy
              ? t("organization_skills_removing")
              : skills.length === 1
                ? t("organization_skills_remove_action")
                : t("organization_skills_remove_confirm", { count: String(skills.length) })}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
