"use client";

import { useSuspenseQuery } from "@tanstack/react-query";
import {
  BookOpenCheck,
  ChevronLeft,
  KeyRound,
  MessageSquare,
  Paperclip,
  Send,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  TextCursorInput
} from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { PageHeader } from "@/components/composites/page-header";
import { SaveStatusIndicator, SaveStatusProvider } from "@/components/composites/save-status";
import {
  SectionedSettings,
  type SettingsSection
} from "@/components/composites/sectioned-settings";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/api/browser";
import { ResourceApiKeysSection } from "@/features/api-keys/resource-api-keys-section";
import { useSpace } from "@/features/spaces/use-space";
import { SkillBindingsSection } from "@/features/skills/skill-bindings-section";
import { appQueryOptions } from "../apps";
import { AttachmentsSection } from "./attachments-section";
import { AiSection } from "./ai-section";
import { GeneralSection } from "./general-section";
import { InputSection } from "./input-section";
import { InstructionsSection } from "./instructions-section";
import { PublishingSection } from "./publishing-section";
import { SecuritySection } from "./security-section";
import { useUpdateApp } from "./use-app";

/** App settings, saved per section (web-next pattern). */
export function AppEditor({ appId }: { appId: string }) {
  const t = useTranslations();
  const { routeId, can } = useSpace();
  const { data: app } = useSuspenseQuery(appQueryOptions(browserApi, appId));
  const update = useUpdateApp(appId);
  const sections: SettingsSection[] = [
    {
      id: "general",
      label: t("general"),
      icon: SlidersHorizontal,
      node: <GeneralSection app={app} />
    },
    { id: "input", label: t("input"), icon: TextCursorInput, node: <InputSection app={app} /> },
    {
      id: "instructions",
      label: t("instructions"),
      icon: MessageSquare,
      node: <InstructionsSection app={app} />
    },
    ...(can("read", "skill")
      ? [
          {
            id: "skills",
            label: t("skills"),
            icon: BookOpenCheck,
            node: (
              <SkillBindingsSection
                resource="app"
                resourceId={app.id}
                canEdit={app.permissions?.includes("edit") ?? false}
                save={(bindings) => update.mutateAsync({ skill_bindings: bindings })}
              />
            )
          }
        ]
      : []),
    {
      id: "attachments",
      label: t("attachments"),
      icon: Paperclip,
      node: <AttachmentsSection app={app} />
    },
    { id: "ai", label: t("ai_settings"), icon: Sparkles, node: <AiSection app={app} /> },
    {
      id: "security",
      label: t("security_and_privacy"),
      icon: ShieldCheck,
      node: <SecuritySection app={app} />
    },
    {
      id: "api-keys",
      label: t("api_keys"),
      icon: KeyRound,
      node: <ResourceApiKeysSection scopeType="app" scopeId={app.id} resourceName={app.name} />
    },
    ...((app.permissions ?? []).includes("publish")
      ? [
          {
            id: "publishing",
            label: t("publishing"),
            icon: Send,
            node: <PublishingSection app={app} />
          }
        ]
      : [])
  ];

  return (
    <SaveStatusProvider>
      <SectionedSettings
        navigationLabel={t("settings")}
        sections={sections}
        header={
          <div className="flex flex-col gap-1 py-3">
            <Link
              href={`/spaces/${routeId}/apps/${app.id}`}
              className="text-muted-foreground hover:text-foreground flex w-fit items-center gap-1 text-sm"
            >
              <ChevronLeft className="size-4" />
              {app.name}
            </Link>
            <PageHeader title={t("edit")}>
              <SaveStatusIndicator />
              <Button asChild variant="outline">
                <Link href={`/spaces/${routeId}/apps/${app.id}`}>{t("done")}</Link>
              </Button>
            </PageHeader>
          </div>
        }
      />
    </SaveStatusProvider>
  );
}
