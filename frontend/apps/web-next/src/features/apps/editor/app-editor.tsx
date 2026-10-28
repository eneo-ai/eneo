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
import { Button as AstryxButton } from "@astryxdesign/core/Button";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/api/browser";
import { ResourceApiKeysSection } from "@/features/api-keys/resource-api-keys-section";
import { editorSummaries } from "@/features/spaces/editor-summaries";
import {
  EditorHeader,
  useCreatedAnnouncement,
  useEditorPhoneIndex
} from "@/features/spaces/editor-header";
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
  const summary = editorSummaries(t);
  const content = t("editor_group_content");
  const modelAndAccess = t("editor_group_model_access");

  const sections: SettingsSection[] = [
    {
      id: "general",
      label: t("general"),
      icon: SlidersHorizontal,
      group: content,
      summary: summary.description(app.description),
      node: <GeneralSection app={app} focusName={created} />
    },
    {
      id: "input",
      label: t("input"),
      icon: TextCursorInput,
      group: content,
      node: <InputSection app={app} />
    },
    {
      id: "instructions",
      label: t("instructions"),
      icon: MessageSquare,
      group: content,
      summary: summary.instructions(app.prompt?.text),
      node: <InstructionsSection app={app} />
    },
    ...(can("read", "skill")
      ? [
          {
            id: "skills",
            label: t("skills"),
            icon: BookOpenCheck,
            group: content,
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
      group: content,
      summary: summary.files(app.attachments.length),
      node: <AttachmentsSection app={app} />
    },
    {
      id: "ai",
      label: t("ai_settings"),
      icon: Sparkles,
      group: modelAndAccess,
      summary: summary.model(app.completion_model),
      node: <AiSection app={app} />
    },
    {
      id: "security",
      label: t("security_and_privacy"),
      icon: ShieldCheck,
      group: modelAndAccess,
      summary: summary.retention(app.data_retention_days),
      node: <SecuritySection app={app} />
    },
    {
      id: "api-keys",
      label: t("api_keys"),
      icon: KeyRound,
      group: modelAndAccess,
      node: <ResourceApiKeysSection scopeType="app" scopeId={app.id} resourceName={app.name} />
    },
    ...((app.permissions ?? []).includes("publish")
      ? [
          {
            id: "publishing",
            label: t("publishing"),
            icon: Send,
            group: modelAndAccess,
            summary: summary.publishing(app.published),
            node: <PublishingSection app={app} />
          }
        ]
      : [])
  ];

  const done = (
    <Button asChild variant="outline" size="sm">
      <Link href={`/spaces/${routeId}/apps/${app.id}`}>{t("done")}</Link>
    </Button>
  );
  const phone = useEditorPhoneIndex({
    section: "apps",
    name: app.name,
    actions: (
      <AstryxButton
        href={`/spaces/${routeId}/apps/${app.id}`}
        variant="secondary"
        label={t("done")}
      />
    ),
    created
  });

  return (
    <SaveStatusProvider>
      <SectionedSettings
        navigationLabel={t("editor_sections_label")}
        sections={sections}
        phone={phone}
        header={<EditorHeader section="apps" name={app.name} actions={done} />}
      />
    </SaveStatusProvider>
  );
}
