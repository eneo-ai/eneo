"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { PageHeader } from "@/components/composites/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useSpace } from "@/features/spaces/use-space";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { SkillForm } from "./skill-form";
import { skillQueryKey } from "./skill-revisions";

export function SpaceSkillNewPage() {
  const t = useTranslations();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { space, routeId } = useSpace();
  const [createdHref, setCreatedHref] = useState<string | null>(null);
  const base = `/spaces/${routeId}/skills`;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 pb-16">
      <PageHeader title={t("skills_library_new_heading")} />
      <Button asChild variant="link" className="w-fit px-0">
        <Link href={base}>{t("skills")}</Link>
      </Button>
      <p className="text-muted-foreground max-w-2xl text-sm">{t("skills_library_new_intro")}</p>
      {createdHref ? (
        <Alert>
          <AlertTitle>{t("organization_skills_created_title")}</AlertTitle>
          <AlertDescription>
            <Button asChild className="mt-3 block w-fit">
              <Link href={createdHref}>{t("organization_skills_open_created_action")}</Link>
            </Button>
          </AlertDescription>
        </Alert>
      ) : (
        <SkillForm
          mode="create"
          onSubmit={async (value) => {
            const skill = await unwrap(
              browserApi.POST("/api/v1/spaces/{space_id}/skills/", {
                params: { path: { space_id: space.id } },
                body: value
              })
            );
            const href = `${base}/${skill.id}`;
            setCreatedHref(href);
            await queryClient.invalidateQueries({
              queryKey: skillQueryKey({ type: "space", spaceId: space.id })
            });
            router.push(href);
          }}
        />
      )}
    </div>
  );
}
