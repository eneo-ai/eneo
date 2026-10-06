"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { PageHeader } from "@/components/composites/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { ORGANIZATION_SKILLS_KEY } from "./organization-skills";
import { SkillForm } from "./skill-form";

export function OrganizationSkillNewPage() {
  const t = useTranslations();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [createdHref, setCreatedHref] = useState<string | null>(null);

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 pb-16">
      <PageHeader title={t("skills_library_new_heading")} />
      <Button asChild variant="link" className="w-fit px-0">
        <Link href="/spaces/organization/skills">{t("skills")}</Link>
      </Button>
      <p className="text-muted-foreground max-w-2xl text-sm">
        {t("organization_skills_new_intro")}
      </p>
      {createdHref ? (
        <Alert>
          <AlertTitle>{t("organization_skills_created_title")}</AlertTitle>
          <AlertDescription>
            {t("organization_skills_created_navigation_failed_description")}
            <Button asChild className="mt-3 block w-fit">
              <Link href={createdHref}>{t("organization_skills_open_created_action")}</Link>
            </Button>
          </AlertDescription>
        </Alert>
      ) : (
        <>
          <Alert role="note">
            <AlertTitle>{t("organization_skills_draft_notice_title")}</AlertTitle>
            <AlertDescription>{t("organization_skills_draft_notice_description")}</AlertDescription>
          </Alert>
          <SkillForm
            mode="create"
            onSubmit={async (value) => {
              const skill = await unwrap(
                browserApi.POST("/api/v1/skills/organization/", { body: value })
              );
              const href = `/spaces/organization/skills/${skill.id}`;
              setCreatedHref(href);
              await queryClient.invalidateQueries({ queryKey: ORGANIZATION_SKILLS_KEY });
              router.push(href);
            }}
          />
        </>
      )}
    </div>
  );
}
