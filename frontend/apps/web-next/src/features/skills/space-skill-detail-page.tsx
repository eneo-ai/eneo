"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { PageHeader } from "@/components/composites/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useSettingSwitch } from "@/features/admin/use-setting-switch";
import { useSpace } from "@/features/spaces/use-space";
import { browserApi } from "@/lib/api/browser";
import { getErrorMessage, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { SkillForm } from "./skill-form";
import { SkillRevisionHistory } from "./skill-revision-history";
import { skillQueryKey } from "./skill-revisions";

type Skill = Schema<"SkillPublic">;

export function SpaceSkillDetailPage({ skillId }: { skillId: string }) {
  const t = useTranslations();
  const { space, routeId, can } = useSpace();
  const queryClient = useQueryClient();
  const [dirty, setDirty] = useState(false);
  const [statusError, setStatusError] = useState<string | null>(null);
  const key = skillQueryKey({ type: "space", spaceId: space.id });
  const base = `/spaces/${routeId}/skills`;
  const skill = useQuery({
    queryKey: [...key, skillId],
    queryFn: (): Promise<Skill> =>
      unwrap(
        browserApi.GET("/api/v1/spaces/{space_id}/skills/{skill_id}/", {
          params: { path: { space_id: space.id, skill_id: skillId } }
        })
      ),
    retry: false
  });

  // Availability saves on toggle and keeps focus while it saves; a failure
  // shows next to the switch (see useSettingSwitch).
  const [active, saveActive, statusBusy] = useSettingSwitch(
    `space-skill:${skillId}:active`,
    skill.data?.is_active ?? false,
    async (value) => {
      const next = await unwrap(
        browserApi.PATCH("/api/v1/spaces/{space_id}/skills/{skill_id}/active/", {
          params: { path: { space_id: space.id, skill_id: skillId } },
          body: { is_active: value }
        })
      );
      queryClient.setQueryData([...key, skillId], next);
      await queryClient.invalidateQueries({ queryKey: key });
    },
    { onSaved: () => {}, onError: (cause) => setStatusError(getErrorMessage(cause, t)) }
  );

  function setActive(value: boolean) {
    setStatusError(null);
    saveActive(value);
  }

  if (skill.isPending) return <p role="status">{t("loading")}</p>;
  if (skill.isError)
    return (
      <Alert variant="destructive" role="alert">
        <AlertTitle>{t("request_failed")}</AlertTitle>
        <AlertDescription>
          <Button variant="outline" onClick={() => void skill.refetch()}>
            {t("retry")}
          </Button>
        </AlertDescription>
      </Alert>
    );
  const value = skill.data;
  const editable = can("edit", "skill");

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-7 pb-16">
      <PageHeader title={value.display_name} />
      <Button asChild variant="link" className="w-fit px-0">
        <Link href={base}>{t("skills")}</Link>
      </Button>
      <section className="grid gap-7 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <div className="space-y-5">
          <div>
            <h2 className="text-lg font-semibold">{t("skills_library_content_heading")}</h2>
            <p className="text-muted-foreground text-sm">
              {t(
                editable
                  ? "skills_library_content_description"
                  : "skills_library_content_read_only_description"
              )}
            </p>
          </div>
          {editable ? (
            <>
              <Alert role="note">
                <AlertTitle>{t("skills_library_revision_notice_title")}</AlertTitle>
                <AlertDescription>
                  {t("skills_library_revision_notice_description")}
                </AlertDescription>
              </Alert>
              <SkillForm
                key={value.current_revision_id}
                mode="revision"
                initialValue={{
                  display_name: value.current_revision.display_name,
                  description: value.current_revision.description,
                  instructions: value.current_revision.instructions
                }}
                onDirtyChange={setDirty}
                onSubmit={async (content) => {
                  await unwrap(
                    browserApi.POST("/api/v1/spaces/{space_id}/skills/{skill_id}/revisions/", {
                      params: { path: { space_id: space.id, skill_id: skillId } },
                      body: content
                    })
                  );
                  await queryClient.invalidateQueries({ queryKey: key });
                }}
              />
            </>
          ) : (
            <div className="space-y-3">
              <p className="text-sm">{value.current_revision.description}</p>
              <pre className="bg-muted/40 max-h-[60dvh] overflow-y-auto rounded-lg border p-4 font-mono text-sm whitespace-pre-wrap">
                {value.current_revision.instructions}
              </pre>
            </div>
          )}
        </div>
        <aside className="space-y-4 rounded-xl border p-5 lg:self-start">
          <div>
            <h2 className="font-semibold">{t("skills_library_status_heading")}</h2>
            <p className="text-muted-foreground mt-1 text-sm">
              {t("skills_library_status_description")}
            </p>
          </div>
          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium">{t("skills_library_availability_switch_label")}</p>
              <p className="text-muted-foreground text-xs">
                {t(
                  active
                    ? "skills_library_active_explanation"
                    : "skills_library_inactive_explanation"
                )}
              </p>
            </div>
            <Switch
              checked={active}
              disabled={!editable}
              aria-busy={statusBusy || undefined}
              aria-label={t("skills_library_availability_switch_label")}
              onCheckedChange={setActive}
            />
          </div>
          {statusError && (
            <Alert variant="destructive" role="alert">
              <AlertTitle>{t("skills_library_status_error")}</AlertTitle>
              <AlertDescription>{statusError}</AlertDescription>
            </Alert>
          )}
        </aside>
      </section>
      <SkillRevisionHistory
        key={value.current_revision_id}
        skill={value}
        unsaved={dirty}
        scope={{ type: "space", spaceId: space.id }}
        allowRestore={editable}
      />
    </div>
  );
}
