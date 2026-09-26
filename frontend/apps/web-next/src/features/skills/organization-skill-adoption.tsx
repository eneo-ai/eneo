"use client";

import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useTranslations } from "next-intl";
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
import { browserApi } from "@/lib/api/browser";
import { getErrorMessage, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { ORGANIZATION_SKILLS_KEY } from "./organization-skills";

type Skill = Schema<"OrganizationSkillPublic">;
type Resource = Schema<"SkillAdoptionResourcePublic">;
type KindFilter = "all" | "assistant" | "app";
type DriftFilter = "all" | "current" | "behind";
const SELECTION_LIMIT = 100;

function resourceKey(resource: Resource) {
  return `${resource.kind}:${resource.resource_id}`;
}
function selectedIds(resources: Resource[]) {
  return {
    assistant_ids: resources
      .filter((resource) => resource.kind === "assistant")
      .map((resource) => resource.resource_id),
    app_ids: resources
      .filter((resource) => resource.kind === "app")
      .map((resource) => resource.resource_id)
  };
}

export function OrganizationSkillAdoption({
  skill,
  rolloutRunning = false
}: {
  skill: Skill;
  rolloutRunning?: boolean;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState<KindFilter>("all");
  const [drift, setDrift] = useState<DriftFilter>("all");
  const [selected, setSelected] = useState<Resource[]>([]);
  const [action, setAction] = useState<"detach" | "advance" | "personal" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [receipt, setReceipt] = useState("");
  const resourcesHeadingId = useId();
  const path = { skill_id: skill.id };
  const bindings = useInfiniteQuery({
    queryKey: [...ORGANIZATION_SKILLS_KEY, skill.id, "adoption", search, kind, drift],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      unwrap(
        browserApi.GET("/api/v1/skills/organization/{skill_id}/adoption/", {
          params: {
            path,
            query: {
              limit: 100,
              cursor: pageParam,
              query: search || undefined,
              kind: kind === "all" ? undefined : kind,
              drift: drift === "all" ? undefined : drift
            }
          }
        })
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    retry: false
  });
  const published = useQuery({
    queryKey: [...ORGANIZATION_SKILLS_KEY, skill.id, "published"],
    enabled: skill.published_revision_number !== null,
    queryFn: () =>
      unwrap(browserApi.GET("/api/v1/skills/catalogue/{skill_id}/", { params: { path } })),
    retry: false
  });
  const revisionId =
    skill.published_revision_number === skill.current_revision_number
      ? skill.current_revision_id
      : published.data?.revision_id;
  const summary = bindings.data?.pages[0]?.summary;
  const items = bindings.data?.pages.flatMap((page) => page.items) ?? [];
  const selectedBehind = selected.filter((resource) => resource.drift === "behind");
  const canAdvance = Boolean(revisionId) && !skill.execution_blocked && !rolloutRunning;

  function searchSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    setSelected([]);
    setSearch(searchInput.trim());
  }

  function toggle(resource: Resource, checked: boolean) {
    setSelected((current) =>
      checked
        ? [
            ...current.filter((item) => resourceKey(item) !== resourceKey(resource)),
            resource
          ].slice(0, SELECTION_LIMIT)
        : current.filter((item) => resourceKey(item) !== resourceKey(resource))
    );
  }

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: [...ORGANIZATION_SKILLS_KEY, skill.id] });
  }

  async function confirm() {
    if (!action || busy || rolloutRunning) return;
    setBusy(true);
    setError(null);
    try {
      if (action === "personal") {
        const pin = summary?.personal_chat;
        if (!pin || !revisionId) return;
        const result = await unwrap(
          browserApi.POST("/api/v1/skills/organization/{skill_id}/personal-chat/advance/", {
            params: { path },
            body: {
              expected_pinned_revision_id: pin.revision_id,
              expected_published_revision_id: revisionId
            }
          })
        );
        setReceipt(
          t("organization_skills_advance_announcement", {
            version: String(result.to_revision_number)
          })
        );
      } else if (action === "detach") {
        if (selected.length === 0) return;
        const result = await unwrap(
          browserApi.POST("/api/v1/skills/organization/{skill_id}/detach/", {
            params: { path },
            body: selectedIds(selected)
          })
        );
        setReceipt(
          t("organization_skills_adoption_detached_success", {
            assistants: String(result.assistant_count),
            apps: String(result.app_count)
          })
        );
        setSelected([]);
      } else {
        if (!revisionId || !canAdvance || selected.length === 0) return;
        const ids = selectedIds(selectedBehind);
        let advanced = 0;
        let concurrent = 0;
        let incompatible = 0;
        const processed = new Set<string>();
        if (ids.assistant_ids.length) {
          const result = await unwrap(
            browserApi.POST("/api/v1/skills/organization/{skill_id}/assistants/advance/", {
              params: { path },
              body: {
                expected_published_revision_id: revisionId,
                cursor: null,
                assistant_ids: ids.assistant_ids
              }
            })
          );
          advanced += result.counts.advanced;
          concurrent += result.counts.concurrent_change;
          incompatible += result.counts.incompatible;
          result.outcomes.forEach((outcome) => processed.add(outcome.assistant_id));
        }
        if (ids.app_ids.length) {
          try {
            const result = await unwrap(
              browserApi.POST("/api/v1/skills/organization/{skill_id}/apps/advance/", {
                params: { path },
                body: {
                  expected_published_revision_id: revisionId,
                  cursor: null,
                  app_ids: ids.app_ids
                }
              })
            );
            advanced += result.counts.advanced;
            concurrent += result.counts.concurrent_change;
            incompatible += result.counts.incompatible;
            result.outcomes.forEach((outcome) => processed.add(outcome.app_id));
          } catch (cause) {
            if (!ids.assistant_ids.length) throw cause;
            setSelected(
              selected.filter(
                (resource) => resource.kind === "app" && ids.app_ids.includes(resource.resource_id)
              )
            );
            const unprocessed = selected.filter(
              (resource) => resource.kind !== "app" && !processed.has(resource.resource_id)
            ).length;
            setReceipt(
              `${t("organization_skills_adoption_advanced_success", {
                advanced: String(advanced),
                unprocessed: String(unprocessed),
                concurrent: String(concurrent),
                incompatible: String(incompatible)
              })} ${t("organization_skills_adoption_advance_partial")}`
            );
            setAction(null);
            await refresh();
            return;
          }
        }
        const unprocessed = selected.filter(
          (resource) => !processed.has(resource.resource_id)
        ).length;
        setReceipt(
          t("organization_skills_adoption_advanced_success", {
            advanced: String(advanced),
            unprocessed: String(unprocessed),
            concurrent: String(concurrent),
            incompatible: String(incompatible)
          })
        );
        setSelected([]);
      }
      setAction(null);
      await refresh();
    } catch (cause) {
      setError(getErrorMessage(cause, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      id="organization-skill-adoption-heading"
      className="scroll-mt-24 space-y-5"
      aria-labelledby="organization-skill-adoption-title"
    >
      <div>
        <h2 id="organization-skill-adoption-title" className="text-lg font-semibold">
          {t("organization_skills_adoption_heading")}
        </h2>
        <p className="text-muted-foreground text-sm">
          {t("organization_skills_adoption_description")}
        </p>
      </div>
      <p role="status" className={receipt ? "text-sm" : "sr-only"}>
        {receipt}
      </p>
      {bindings.isPending ? (
        <p role="status">{t("organization_skills_adoption_loading")}</p>
      ) : bindings.isError && !bindings.data ? (
        <Alert variant="destructive" role="alert">
          <AlertTitle>{t("organization_skills_adoption_error_title")}</AlertTitle>
          <AlertDescription>
            <p>{t("organization_skills_adoption_error")}</p>
            <Button variant="outline" className="mt-2" onClick={() => void bindings.refetch()}>
              {t("retry")}
            </Button>
          </AlertDescription>
        </Alert>
      ) : (
        <>
          {summary && (
            <>
              <dl className="grid grid-cols-2 gap-4 border-y py-4 sm:grid-cols-4">
                {(
                  [
                    ["organization_skills_adoption_assistants_label", summary.assistant_count],
                    ["organization_skills_adoption_apps_label", summary.app_count],
                    ["organization_skills_adoption_spaces_label", summary.distinct_space_count],
                    ["organization_skills_adoption_behind_label", summary.behind_published_count]
                  ] as const
                ).map(([label, count]) => (
                  <div key={label}>
                    <dt className="text-muted-foreground text-sm">{t(label)}</dt>
                    <dd className="text-xl font-semibold tabular-nums">{count}</dd>
                  </div>
                ))}
              </dl>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="rounded-lg border p-4">
                  <h3 className="font-medium">
                    {t("organization_skills_adoption_personal_chat_heading")}
                  </h3>
                  <p className="text-muted-foreground mt-2 text-sm">
                    {summary.personal_chat
                      ? t("organization_skills_adoption_personal_chat_pinned", {
                          version: String(summary.personal_chat.revision_number)
                        })
                      : t("organization_skills_adoption_personal_chat_not_pinned")}
                  </p>
                  {summary.personal_chat &&
                    summary.personal_chat.revision_id !== revisionId &&
                    canAdvance && (
                      <Button
                        className="mt-3"
                        variant="outline"
                        size="sm"
                        onClick={() => setAction("personal")}
                      >
                        {t("organization_skills_adoption_personal_chat_advance_action")}
                      </Button>
                    )}
                </div>
                <div className="rounded-lg border p-4">
                  <h3 className="font-medium">
                    {t("organization_skills_adoption_revision_breakdown_heading")}
                  </h3>
                  <p className="text-muted-foreground mt-1 text-xs">
                    {t("organization_skills_adoption_revision_breakdown_description")}
                  </p>
                  <ul className="mt-3 space-y-1 text-sm">
                    {summary.revision_counts.map((entry) => (
                      <li key={entry.revision_id} className="flex justify-between gap-3">
                        <span>
                          {t("organization_skills_version", {
                            version: String(entry.revision_number)
                          })}
                        </span>
                        <span>
                          {entry.assistant_count} {t("assistants")} · {entry.app_count} {t("apps")}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </>
          )}
          <div className="space-y-3">
            <h3 id={resourcesHeadingId} className="font-medium">
              {t("organization_skills_adoption_resources_heading")}
            </h3>
            <p className="text-muted-foreground text-sm">
              {t("organization_skills_adoption_resources_description")}
            </p>
            <form className="flex max-w-2xl gap-2" role="search" onSubmit={searchSubmit}>
              <Input
                type="search"
                value={searchInput}
                placeholder={t("organization_skills_adoption_search_placeholder")}
                aria-label={t("organization_skills_adoption_search_placeholder")}
                onChange={(event) => setSearchInput(event.target.value)}
              />
              <Button variant="outline" type="submit">
                {t("search")}
              </Button>
            </form>
            <div className="flex flex-wrap gap-3">
              <label className="flex items-center gap-2 text-sm">
                {t("organization_skills_adoption_filter_kind_label")}
                <select
                  className="bg-background rounded-md border p-2"
                  value={kind}
                  onChange={(event) => {
                    setKind(event.target.value as KindFilter);
                    setSelected([]);
                  }}
                >
                  <option value="all">{t("organization_skills_adoption_filter_kind_all")}</option>
                  <option value="assistant">
                    {t("organization_skills_adoption_resource_assistant")}
                  </option>
                  <option value="app">{t("organization_skills_adoption_resource_app")}</option>
                </select>
              </label>
              <label className="flex items-center gap-2 text-sm">
                {t("organization_skills_adoption_filter_status_label")}
                <select
                  className="bg-background rounded-md border p-2"
                  value={drift}
                  onChange={(event) => {
                    setDrift(event.target.value as DriftFilter);
                    setSelected([]);
                  }}
                >
                  <option value="all">{t("organization_skills_adoption_filter_status_all")}</option>
                  <option value="current">{t("organization_skills_adoption_drift_current")}</option>
                  <option value="behind">{t("organization_skills_adoption_drift_behind")}</option>
                </select>
              </label>
              {(search || kind !== "all" || drift !== "all") && (
                <Button
                  variant="ghost"
                  onClick={() => {
                    setSearch("");
                    setSearchInput("");
                    setKind("all");
                    setDrift("all");
                    setSelected([]);
                  }}
                >
                  {t("organization_skills_adoption_clear_filters")}
                </Button>
              )}
            </div>
            {selected.length > 0 && (
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-muted-foreground text-sm">
                  {t("organization_skills_adoption_selection_count", {
                    count: String(selected.length),
                    limit: String(SELECTION_LIMIT)
                  })}
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={rolloutRunning}
                  onClick={() => setAction("detach")}
                >
                  {t("organization_skills_adoption_detach_selected")}
                </Button>
                {canAdvance && selectedBehind.length > 0 && (
                  <Button size="sm" onClick={() => setAction("advance")}>
                    {t("organization_skills_adoption_advance_selected")}
                  </Button>
                )}
                <Button variant="ghost" size="sm" onClick={() => setSelected([])}>
                  {t("clear")}
                </Button>
              </div>
            )}
            {items.length === 0 ? (
              <p className="text-muted-foreground rounded-lg border border-dashed p-8 text-center text-sm">
                {search || kind !== "all" || drift !== "all"
                  ? t("organization_skills_adoption_filtered_empty")
                  : t("organization_skills_adoption_resources_empty")}
              </p>
            ) : (
              <div className="overflow-x-auto rounded-lg border">
                <table
                  className="w-full min-w-[650px] text-sm"
                  aria-labelledby={resourcesHeadingId}
                >
                  <thead>
                    <tr className="border-b text-left">
                      <th className="w-10 p-3">
                        <input
                          type="checkbox"
                          className="accent-primary size-4"
                          aria-label={t("organization_skills_adoption_select_shown", {
                            count: String(Math.min(items.length, SELECTION_LIMIT))
                          })}
                          checked={
                            items.length > 0 &&
                            items
                              .slice(0, SELECTION_LIMIT)
                              .every((item) =>
                                selected.some((row) => resourceKey(row) === resourceKey(item))
                              )
                          }
                          onChange={(event) =>
                            setSelected(event.target.checked ? items.slice(0, SELECTION_LIMIT) : [])
                          }
                        />
                      </th>
                      <th className="p-3">{t("organization_skills_adoption_resource_column")}</th>
                      <th className="p-3">{t("organization_skills_adoption_space_column")}</th>
                      <th className="p-3">
                        {t("organization_skills_adoption_pinned_revision_column")}
                      </th>
                      <th className="p-3">{t("organization_skills_adoption_status_column")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((resource) => (
                      <tr key={resourceKey(resource)} className="border-b last:border-0">
                        <td className="p-3">
                          <input
                            type="checkbox"
                            className="accent-primary size-4"
                            aria-label={t("organization_skills_adoption_select_resource", {
                              name: resource.name
                            })}
                            checked={selected.some(
                              (row) => resourceKey(row) === resourceKey(resource)
                            )}
                            disabled={
                              selected.length >= SELECTION_LIMIT &&
                              !selected.some((row) => resourceKey(row) === resourceKey(resource))
                            }
                            onChange={(event) => toggle(resource, event.target.checked)}
                          />
                        </td>
                        <td className="p-3">
                          <p className="font-medium">
                            {resource.can_open === false ? (
                              resource.name
                            ) : (
                              <Link
                                className="underline-offset-2 hover:underline"
                                href={
                                  resource.kind === "assistant"
                                    ? `/spaces/${resource.space_id}/assistants/${resource.resource_id}/edit`
                                    : `/spaces/${resource.space_id}/apps/${resource.resource_id}`
                                }
                              >
                                {resource.name}
                              </Link>
                            )}
                          </p>
                          <p className="text-muted-foreground text-xs">
                            {t(
                              resource.kind === "assistant"
                                ? "organization_skills_adoption_resource_assistant"
                                : "organization_skills_adoption_resource_app"
                            )}
                          </p>
                        </td>
                        <td className="p-3">
                          {resource.space_name}
                          {resource.owner_name && (
                            <p className="text-muted-foreground text-xs">{resource.owner_name}</p>
                          )}
                        </td>
                        <td className="p-3 tabular-nums">
                          {t("organization_skills_version", {
                            version: String(resource.revision_number)
                          })}
                        </td>
                        <td className="p-3">
                          <Badge variant={resource.drift === "behind" ? "outline" : "secondary"}>
                            {t(`organization_skills_adoption_drift_${resource.drift}`)}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {bindings.hasNextPage && (
              <Button
                variant="outline"
                disabled={bindings.isFetchingNextPage}
                onClick={() => void bindings.fetchNextPage()}
              >
                {bindings.isFetchingNextPage
                  ? t("organization_skills_adoption_loading_more")
                  : t("organization_skills_adoption_load_more")}
              </Button>
            )}
            {bindings.isFetchNextPageError && (
              <Alert variant="destructive" role="alert">
                <AlertTitle>{t("organization_skills_adoption_load_more_error")}</AlertTitle>
                <AlertDescription>
                  <Button variant="outline" onClick={() => void bindings.fetchNextPage()}>
                    {t("retry")}
                  </Button>
                </AlertDescription>
              </Alert>
            )}
          </div>
        </>
      )}
      <AlertDialog
        open={action !== null}
        onOpenChange={(open) => {
          if (!open && !busy) {
            setAction(null);
            setError(null);
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {t(
                action === "detach"
                  ? "organization_skills_adoption_detach_title"
                  : action === "personal"
                    ? "organization_skills_advance_title"
                    : "organization_skills_adoption_advance_title"
              )}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {action === "personal"
                ? t("organization_skills_advance_description", {
                    pinned: String(summary?.personal_chat?.revision_number ?? ""),
                    published: String(skill.published_revision_number ?? "")
                  })
                : t(
                    action === "detach"
                      ? "organization_skills_adoption_detach_description"
                      : "organization_skills_adoption_advance_description",
                    { count: String(selected.length) }
                  )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {action !== "personal" && (
            <ul className="max-h-52 divide-y overflow-y-auto text-sm">
              {selected.map((resource) => (
                <li key={resourceKey(resource)} className="py-2">
                  {resource.name}
                </li>
              ))}
            </ul>
          )}
          {error && (
            <Alert variant="destructive" role="alert">
              <AlertTitle>
                {t(
                  action === "detach"
                    ? "organization_skills_adoption_detach_error"
                    : "organization_skills_adoption_advance_error"
                )}
              </AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={busy}>{t("cancel")}</AlertDialogCancel>
            <Button
              variant={action === "detach" ? "destructive" : "default"}
              disabled={busy || rolloutRunning}
              onClick={() => void confirm()}
            >
              {busy
                ? t(
                    action === "detach"
                      ? "organization_skills_adoption_detaching"
                      : "organization_skills_adoption_advancing"
                  )
                : t(
                    action === "detach"
                      ? "organization_skills_adoption_detach_selected"
                      : action === "personal"
                        ? "organization_skills_advance_confirm"
                        : "organization_skills_adoption_advance_selected"
                  )}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  );
}
