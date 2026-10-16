"use client";

import { useSuspenseQuery } from "@tanstack/react-query";
import {
  BookOpenCheck,
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
import { SaveStatusProvider } from "@/components/composites/save-status";
import {
  SectionedSettings,
  type SettingsSection
} from "@/components/composites/sectioned-settings";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/api/browser";
import { ResourceApiKeysSection } from "@/features/api-keys/resource-api-keys-section";
import { EditorHeader, useCreatedAnnouncement } from "@/features/spaces/editor-header";
import { useJustCreated } from "@/features/spaces/just-created";
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

/**
 * App settings, saved per section (web-next pattern). The editor owns the
 * surface (see AssistantEditor); "Klar" leads to the app's run page. Opened
 * right after "Skapa app", it focuses the (default) name and announces the
 * creation.
 */
export function AppEditor({ appId }: { appId: string }) {
  const t = useTranslations();
  const { routeId, can } = useSpace();
  const { data: app } = useSuspenseQuery(appQueryOptions(browserApi, appId));
  const update = useUpdateApp(appId);
  const created = useJustCreated("app", appId);
  useCreatedAnnouncement(created, t("app_created_announcement"));

  const sections: SettingsSection[] = [
    {
      id: "general",
      label: t("general"),
      icon: SlidersHorizontal,
      node: <GeneralSection app={app} focusName={created} />
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
        navigationLabel={t("editor_sections_label")}
        sections={sections}
        header={
          <EditorHeader
            section="apps"
            name={app.name}
            actions={
              <Button asChild variant="outline" size="sm">
                <Link href={`/spaces/${routeId}/apps/${app.id}`}>{t("done")}</Link>
              </Button>
            }
          />
        }
      />
    </SaveStatusProvider>
  );
}
