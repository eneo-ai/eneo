"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { PageHeader } from "@/components/composites/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { ORGANIZATION_SKILLS_KEY, type SkillRemovalResult } from "./organization-skills";
import { SkillRemovalDialog } from "./organization-skills-page";
import { SkillForm } from "./skill-form";
import { SkillRevisionHistory } from "./skill-revision-history";
import { OrganizationSkillExecution } from "./organization-skill-execution";
import { OrganizationSkillPublication } from "./organization-skill-publication";
import { OrganizationSkillAdoption } from "./organization-skill-adoption";

const LIST_PATH = "/spaces/organization/skills";

export function OrganizationSkillDetailPage({ skillId }: { skillId: string }) {
  const t = useTranslations();
  const locale = useLocale();
  const queryClient = useQueryClient();
  const [dirty, setDirty] = useState(false);
  const [rolloutRunning, setRolloutRunning] = useState(false);
  const [removalOpen, setRemovalOpen] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const skill = useQuery({
    queryKey: [...ORGANIZATION_SKILLS_KEY, skillId],
    queryFn: () =>
      unwrap(
        browserApi.GET("/api/v1/skills/organization/{skill_id}/", {
          params: { path: { skill_id: skillId } }
        })
      ),
    retry: false
  });

  async function removed(result: SkillRemovalResult) {
    setRemovalOpen(false);
    setAnnouncement(
      t("organization_skills_removed_success", { count: String(result.removed_ids.length) })
    );
    await queryClient.invalidateQueries({ queryKey: ORGANIZATION_SKILLS_KEY });
  }

  if (skill.isPending)
    return (
      <p role="status" className="text-muted-foreground p-6 text-sm">
        {t("loading")}
      </p>
    );
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

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-7 pb-16">
      <PageHeader title={value.display_name}>
        {!value.removed_at && (
          <Button
            variant="destructive"
            disabled={dirty || rolloutRunning}
            onClick={() => setRemovalOpen(true)}
          >
            {t("organization_skills_remove_action")}
          </Button>
        )}
      </PageHeader>
      <Button asChild variant="link" className="w-fit px-0">
        <Link href={LIST_PATH}>{t("skills")}</Link>
      </Button>
      <p role="status" className={announcement ? "text-sm" : "sr-only"}>
        {announcement}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={value.publication_state === "published" ? "secondary" : "outline"}>
          {t(
            value.execution_blocked
              ? "organization_skills_status_blocked"
              : `organization_skills_status_${value.publication_state}`
          )}
        </Badge>
        <span className="text-muted-foreground text-sm">{value.slug}</span>
        <span className="text-muted-foreground text-sm">
          {t("organization_skills_version", { version: String(value.current_revision_number) })}
        </span>
      </div>
      {value.removed_at ? (
        <>
          <Alert>
            <AlertTitle>
              {t("organization_skills_removed_at", {
                time: new Date(value.removed_at).toLocaleString(locale)
              })}
            </AlertTitle>
            <AlertDescription>{t("organization_skills_removed_description")}</AlertDescription>
          </Alert>
          <section className="space-y-3" aria-labelledby="organization-skill-content-heading">
            <h2 id="organization-skill-content-heading" className="text-lg font-semibold">
              {t("skills_library_content_heading")}
            </h2>
            <p>{value.current_revision.description}</p>
            <pre className="bg-muted/40 max-h-[60dvh] overflow-y-auto rounded-lg border p-4 font-mono text-sm whitespace-pre-wrap">
              {value.current_revision.instructions}
            </pre>
          </section>
        </>
      ) : (
        <section className="space-y-5" aria-labelledby="organization-skill-content-heading">
          <div>
            <h2 id="organization-skill-content-heading" className="text-lg font-semibold">
              {t("skills_library_content_heading")}
            </h2>
            <p className="text-muted-foreground text-sm">
              {t("organization_skills_content_description")}
            </p>
          </div>
          <Alert role="note">
            <AlertTitle>{t("skills_library_revision_notice_title")}</AlertTitle>
            <AlertDescription>{t("skills_library_revision_notice_description")}</AlertDescription>
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
                browserApi.POST("/api/v1/skills/organization/{skill_id}/revisions/", {
                  params: { path: { skill_id: skillId } },
                  body: content
                })
              );
              await queryClient.invalidateQueries({ queryKey: ORGANIZATION_SKILLS_KEY });
            }}
          />
        </section>
      )}
      {!value.removed_at && (
        <OrganizationSkillPublication
          skill={value}
          unsaved={dirty}
          onRolloutRunningChange={setRolloutRunning}
        />
      )}
      {value.first_published_at && <OrganizationSkillExecution skillId={skillId} />}
      {!value.removed_at && (
        <OrganizationSkillAdoption skill={value} rolloutRunning={rolloutRunning} />
      )}
      <SkillRevisionHistory key={value.current_revision_id} skill={value} unsaved={dirty} />
      {removalOpen && (
        <SkillRemovalDialog
          skills={[value]}
          onClose={() => setRemovalOpen(false)}
          onRemoved={removed}
          onExclude={() => setRemovalOpen(false)}
        />
      )}
    </div>
  );
}
