"use client";

import { IconButton } from "@astryxdesign/core/IconButton";
import { pixel, proportional, Table, type TableColumn } from "@astryxdesign/core/Table";
import { VisuallyHidden } from "@astryxdesign/core/VisuallyHidden";
import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpenCheck, Plus, Search, Trash2 } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useRef, useState, type SubmitEvent } from "react";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "@/components/ui/alert-dialog";
import { EmptyState } from "@/components/composites/empty-state";
import { LoadingState } from "@/components/composites/loading-state";
import { StatusLabel } from "@/components/composites/status-label";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { browserApi } from "@/lib/api/browser";
import { getErrorMessage, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { PageHeader } from "@/components/composites/page-header";
import { ClientTime } from "@/components/composites/client-time";
import { useRemovalMutation } from "@/features/spaces/removal";
import { SpaceTableFrame } from "@/features/spaces/table-frame";
import { useSpace } from "@/features/spaces/use-space";
import { skillQueryKey } from "./skill-revisions";

type Skill = Schema<"SkillSparse">;
const PAGE_SIZE = 25;

export function SpaceSkillsPage() {
  const t = useTranslations();
  const { space, routeId, can } = useSpace();
  const queryClient = useQueryClient();
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [deleteTarget, setDeleteTarget] = useState<Skill | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const base = `/spaces/${routeId}/skills`;
  const key = skillQueryKey({ type: "space", spaceId: space.id });
  const skills = useInfiniteQuery({
    queryKey: [...key, search],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      unwrap(
        browserApi.GET("/api/v1/spaces/{space_id}/skills/", {
          params: {
            path: { space_id: space.id },
            query: { limit: PAGE_SIZE, cursor: pageParam, q: search || undefined }
          }
        })
      ),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    retry: false
  });
  const items = skills.data?.pages.flatMap((page) => page.items) ?? [];

  function submitSearch(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    setSearch(searchInput.trim());
  }

  // The error stays in the dialog, next to the action that failed.
  const removeSkill = useRemovalMutation({
    mutationFn: (skill: Skill) =>
      unwrap(
        browserApi.DELETE("/api/v1/spaces/{space_id}/skills/{skill_id}/", {
          params: { path: { space_id: space.id, skill_id: skill.id } }
        })
      ),
    refresh: () => queryClient.invalidateQueries({ queryKey: key }),
    onRemoved: () => {
      setDeleteTarget(null);
      setAnnouncement(t("skills_library_deleted_success"));
    },
    onError: (cause) => setDeleteError(getErrorMessage(cause, t)),
    focusTarget: headingRef
  });
  const deleting = removeSkill.isPending;

  function deleteSkill() {
    if (!deleteTarget || deleting) return;
    setDeleteError(null);
    removeSkill.mutate(deleteTarget);
  }

  const columns: TableColumn<Skill>[] = [
    {
      key: "display_name",
      header: t("name"),
      width: proportional(2),
      renderCell: (skill) => (
        <span className="flex min-w-0 flex-col">
          <Link
            className="text-ax-text focus-visible:outline-ring rounded-ax-inner inline-flex min-h-6 items-center font-semibold hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11"
            href={`${base}/${skill.id}`}
          >
            {skill.display_name}
          </Link>
          <span className="text-ax-text-secondary text-xs break-all">{skill.slug}</span>
        </span>
      )
    },
    {
      key: "description",
      header: t("description"),
      width: proportional(3),
      renderCell: (skill) => <span className="text-ax-text-secondary">{skill.description}</span>
    },
    {
      key: "status",
      header: t("status"),
      width: proportional(1),
      renderCell: (skill) => (
        <StatusLabel
          status={skill.is_active ? "success" : "neutral"}
          label={t(skill.is_active ? "skills_available_status" : "skills_unavailable_status")}
        />
      )
    },
    {
      key: "revision",
      header: t("skills_library_revision_column"),
      width: proportional(1),
      renderCell: (skill) =>
        t("skills_revision_label", { revision: String(skill.current_revision_number) })
    },
    {
      key: "updated_at",
      header: t("skills_library_updated_column"),
      width: proportional(1),
      renderCell: (skill) => <ClientTime value={skill.updated_at} format="date_time" />
    },
    ...(can("delete", "skill")
      ? [
          {
            key: "actions",
            header: <VisuallyHidden>{t("actions")}</VisuallyHidden>,
            width: pixel(56),
            align: "end" as const,
            renderCell: (skill: Skill) => (
              <IconButton
                label={t("skills_library_delete_aria", { name: skill.display_name })}
                icon={<Trash2 aria-hidden="true" />}
                variant="ghost"
                onClick={() => {
                  setDeleteError(null);
                  setDeleteTarget(skill);
                }}
              />
            )
          }
        ]
      : [])
  ];

  return (
    <div className="flex w-full max-w-5xl flex-col gap-6 pb-16">
      <PageHeader
        headingLevel={2}
        headingRef={headingRef}
        title={t("skills")}
        description={t("skills_library_intro")}
        tour="space-skills"
        actions={
          can("create", "skill") ? (
            <Button asChild>
              <Link href={`${base}/new`}>
                <Plus className="size-4" />
                {t("skills_library_create")}
              </Link>
            </Button>
          ) : undefined
        }
      />
      <p role="status" className={announcement ? "text-sm" : "sr-only"}>
        {announcement}
      </p>
      {items.length > 0 || search || skills.isPending ? (
        <form role="search" className="flex max-w-md gap-2" onSubmit={submitSearch}>
          <div className="relative min-w-0 flex-1">
            <Search className="text-muted-foreground absolute top-1/2 left-3 size-4 -translate-y-1/2" />
            <Input
              type="search"
              className="pl-9"
              value={searchInput}
              placeholder={t("skills_library_search_placeholder")}
              aria-label={t("skills_library_search_placeholder")}
              onChange={(event) => setSearchInput(event.target.value)}
            />
          </div>
          <Button type="submit" variant="outline">
            {t("search")}
          </Button>
        </form>
      ) : null}
      {skills.isPending ? (
        <LoadingState rows={3} />
      ) : skills.isError && !skills.data ? (
        <Alert variant="destructive" role="alert">
          <AlertTitle>{t("request_failed")}</AlertTitle>
          <AlertDescription>
            <Button variant="outline" onClick={() => void skills.refetch()}>
              {t("retry")}
            </Button>
          </AlertDescription>
        </Alert>
      ) : items.length === 0 ? (
        <EmptyState
          icon={<BookOpenCheck />}
          headingLevel={3}
          title={search ? t("skills_library_no_results") : t("skills_library_empty_title")}
          description={search ? undefined : t("skills_library_empty_description")}
          actions={
            search ? (
              <Button
                variant="outline"
                onClick={() => {
                  setSearch("");
                  setSearchInput("");
                }}
              >
                {t("clear")}
              </Button>
            ) : can("create", "skill") ? (
              <Button asChild>
                <Link href={`${base}/new`}>{t("skills_library_create_first")}</Link>
              </Button>
            ) : undefined
          }
        />
      ) : (
        <>
          <SpaceTableFrame>
            <Table data={items} columns={columns} idKey="id" verticalAlign="top" />
          </SpaceTableFrame>
          {skills.hasNextPage && (
            <Button
              variant="outline"
              className="self-center"
              disabled={skills.isFetchingNextPage}
              onClick={() => void skills.fetchNextPage()}
            >
              {skills.isFetchingNextPage ? t("loading") : t("load_more")}
            </Button>
          )}
          {skills.isFetchNextPageError && (
            <Alert variant="destructive" role="alert">
              <AlertTitle>{t("request_failed")}</AlertTitle>
              <AlertDescription>
                <Button variant="outline" onClick={() => void skills.fetchNextPage()}>
                  {t("retry")}
                </Button>
              </AlertDescription>
            </Alert>
          )}
        </>
      )}
      <AlertDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open && !deleting) setDeleteTarget(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("skills_library_delete_title")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("skills_library_delete_description", { name: deleteTarget?.display_name ?? "" })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          {deleteError && (
            <Alert variant="destructive" role="alert">
              <AlertTitle>{t("request_failed")}</AlertTitle>
              <AlertDescription>{deleteError}</AlertDescription>
            </Alert>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>{t("cancel")}</AlertDialogCancel>
            <Button variant="destructive" disabled={deleting} onClick={deleteSkill}>
              {deleting ? t("skills_library_deleting") : t("delete")}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
