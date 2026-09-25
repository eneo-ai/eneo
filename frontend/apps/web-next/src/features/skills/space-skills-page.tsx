"use client";

import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpenCheck, Plus, Search, Trash2 } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "@/components/ui/alert-dialog";
import { PageHeader } from "@/components/composites/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { browserApi } from "@/lib/api/browser";
import { getErrorMessage, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { useSpace } from "@/features/spaces/use-space";
import { skillQueryKey } from "./skill-revisions";

type Skill = Schema<"SkillSparse">;
const PAGE_SIZE = 25;

export function SpaceSkillsPage() {
  const t = useTranslations();
  const locale = useLocale();
  const { space, routeId, can } = useSpace();
  const queryClient = useQueryClient();
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<Skill | null>(null);
  const [deleting, setDeleting] = useState(false);
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

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSearch(searchInput.trim());
  }

  async function deleteSkill() {
    if (!deleteTarget || deleting) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await unwrap(
        browserApi.DELETE("/api/v1/spaces/{space_id}/skills/{skill_id}/", {
          params: { path: { space_id: space.id, skill_id: deleteTarget.id } }
        })
      );
      setDeleteTarget(null);
      setAnnouncement(t("skills_library_deleted_success"));
      await queryClient.invalidateQueries({ queryKey: key });
    } catch (cause) {
      setDeleteError(getErrorMessage(cause, t));
    } finally {
      setDeleting(false);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 pb-16">
      <PageHeader title={t("skills")} tour="space-skills">
        {can("create", "skill") && (
          <Button asChild>
            <Link href={`${base}/new`}>
              <Plus className="size-4" />
              {t("skills_library_create")}
            </Link>
          </Button>
        )}
      </PageHeader>
      <p className="text-muted-foreground max-w-2xl text-sm">{t("skills_library_intro")}</p>
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
        <p role="status">{t("loading")}</p>
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
        <div className="flex max-w-3xl flex-col items-center gap-3 rounded-xl border border-dashed p-10 text-center">
          <BookOpenCheck className="text-muted-foreground size-9" />
          <h2 className="font-medium">
            {search ? t("skills_library_no_results") : t("skills_library_empty_title")}
          </h2>
          {!search && (
            <p className="text-muted-foreground text-sm">{t("skills_library_empty_description")}</p>
          )}
          {search ? (
            <Button
              variant="ghost"
              onClick={() => {
                setSearch("");
                setSearchInput("");
              }}
            >
              {t("clear")}
            </Button>
          ) : (
            can("create", "skill") && (
              <Button asChild>
                <Link href={`${base}/new`}>{t("skills_library_create_first")}</Link>
              </Button>
            )
          )}
        </div>
      ) : (
        <>
          <div className="overflow-x-auto rounded-xl border">
            <table className="w-full min-w-[650px] text-sm">
              <thead>
                <tr className="border-b text-left">
                  <th className="p-3">{t("name")}</th>
                  <th className="p-3">{t("description")}</th>
                  <th className="p-3">{t("status")}</th>
                  <th className="p-3">{t("skills_library_revision_column")}</th>
                  <th className="p-3">{t("skills_library_updated_column")}</th>
                  {can("delete", "skill") && (
                    <th className="p-3">
                      <span className="sr-only">{t("actions")}</span>
                    </th>
                  )}
                </tr>
              </thead>
              <tbody>
                {items.map((skill) => (
                  <tr key={skill.id} className="border-b align-top last:border-0">
                    <td className="p-3">
                      <Link
                        className="font-medium underline-offset-2 hover:underline"
                        href={`${base}/${skill.id}`}
                      >
                        {skill.display_name}
                      </Link>
                      <p className="text-muted-foreground text-xs break-all">{skill.slug}</p>
                    </td>
                    <td className="text-muted-foreground max-w-sm p-3">{skill.description}</td>
                    <td className="p-3">
                      <Badge variant={skill.is_active ? "secondary" : "outline"}>
                        {t(
                          skill.is_active ? "skills_available_status" : "skills_unavailable_status"
                        )}
                      </Badge>
                    </td>
                    <td className="p-3">
                      {t("skills_revision_label", {
                        revision: String(skill.current_revision_number)
                      })}
                    </td>
                    <td className="p-3 tabular-nums">
                      {new Date(skill.updated_at).toLocaleString(locale, {
                        dateStyle: "short",
                        timeStyle: "short"
                      })}
                    </td>
                    {can("delete", "skill") && (
                      <td className="p-3">
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={t("skills_library_delete_aria", { name: skill.display_name })}
                          onClick={() => {
                            setDeleteError(null);
                            setDeleteTarget(skill);
                          }}
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
            <Button variant="destructive" disabled={deleting} onClick={() => void deleteSkill()}>
              {deleting ? t("skills_library_deleting") : t("delete")}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
