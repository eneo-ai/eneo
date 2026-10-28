"use client";

import { useSuspenseQuery } from "@tanstack/react-query";
import {
  BookOpen,
  BookOpenCheck,
  Globe,
  KeyRound,
  MessageSquare,
  Paperclip,
  Play,
  Plug,
  Send,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles
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
import { chatPartnerHref } from "../assistants";
import { AiSection } from "./ai-section";
import { GeneralSection } from "./general-section";
import { AttachmentsSection } from "./attachments-section";
import { CapabilitiesSection, selectedCapabilities } from "./capabilities-section";
import { InstructionsSection } from "./instructions-section";
import { KnowledgeSection } from "./knowledge-section";
import { McpSection } from "./mcp-section";
import { PublishingSection } from "./publishing-section";
import { SecuritySection } from "./security-section";
import { assistantQueryOptions, type Assistant, useUpdateAssistant } from "./use-assistant";

/**
 * Assistant settings. Saved per section (web-next pattern; the Svelte app's
 * global draft/diff editor is intentionally not ported). The editor owns the
 * surface: a single full-width column under a sticky header with the
 * breadcrumb back to the space's assistants, the name, the aggregate save
 * state and a shortcut into chat, then the section links. Opened right after
 * "Skapa assistent", it focuses the (default) name and announces the creation.
 */
export function AssistantEditor({ assistantId }: { assistantId: string }) {
  const t = useTranslations();
  const { space, routeId, can } = useSpace();
  const { data: assistant } = useSuspenseQuery(assistantQueryOptions(browserApi, assistantId));
  const update = useUpdateAssistant(assistantId);
  const created = useJustCreated("assistant", assistantId);
  useCreatedAnnouncement(created, t("assistant_created_announcement"));

  const chatHref = chatPartnerHref(routeId, { ...assistant, type: "assistant" as const });

  const hasMcp =
    (space.mcp_servers?.length ?? 0) > 0 || assistant.effective_config?.mcp_enforced === true;
  const permissions = assistant.permissions ?? [];
  const hasPublishing = permissions.includes("publish") || permissions.includes("insight_toggle");
  const summary = editorSummaries(t);
  const content = t("editor_group_content");
  const model = t("editor_group_model");
  const access = t("editor_group_access");

  const sections: SettingsSection[] = [
    {
      id: "general",
      label: t("general"),
      icon: SlidersHorizontal,
      group: content,
      summary: summary.description(assistant.description),
      node: <GeneralSection assistant={assistant} focusName={created} />
    },
    {
      id: "instructions",
      label: t("instructions"),
      icon: MessageSquare,
      group: content,
      summary: summary.instructions(assistant.prompt?.text),
      node: <InstructionsSection assistant={assistant} />
    },
    {
      id: "knowledge",
      label: t("knowledge"),
      icon: BookOpen,
      group: content,
      summary: summary.sources(
        assistant.groups.length +
          assistant.websites.length +
          assistant.integration_knowledge_list.length
      ),
      node: <KnowledgeSection assistant={assistant} />
    },
    ...(can("read", "skill") && (!space.personal || space.default_assistant?.id !== assistant.id)
      ? [
          {
            id: "skills",
            label: t("skills"),
            icon: BookOpenCheck,
            group: content,
            node: (
              <SkillBindingsSection
                resource="assistant"
                resourceId={assistant.id}
                canEdit={permissions.includes("edit")}
                save={(bindings) => update.mutateAsync({ skill_bindings: bindings })}
              />
            )
          }
        ]
      : []),
    ...(hasMcp
      ? [
          {
            id: "mcp",
            label: t("mcp_servers"),
            icon: Plug,
            group: content,
            summary: summary.chosen(assistant.mcp_servers?.length ?? 0),
            node: <McpSection assistant={assistant} />
          }
        ]
      : []),
    {
      id: "ai",
      label: t("ai_settings"),
      icon: Sparkles,
      group: model,
      summary: summary.model(assistant.completion_model),
      node: <AiSection assistant={assistant} />
    },
    {
      id: "capabilities",
      label: t("capabilities"),
      icon: Globe,
      group: model,
      summary: summary.chosen(selectedCapabilities(assistant).length),
      node: <CapabilitiesSection assistant={assistant} />
    },
    {
      id: "attachments",
      label: t("attachments"),
      icon: Paperclip,
      group: model,
      summary: summary.files(assistant.attachments.length),
      node: <AttachmentsSection assistant={assistant} />
    },
    {
      id: "security",
      label: t("security_and_privacy"),
      icon: ShieldCheck,
      group: access,
      summary: summary.retention(assistant.data_retention_days),
      node: <SecuritySection assistant={assistant} />
    },
    {
      id: "api-keys",
      label: t("api_keys"),
      icon: KeyRound,
      group: access,
      node: (
        <ResourceApiKeysSection
          scopeType="assistant"
          scopeId={assistant.id}
          resourceName={assistant.name}
        />
      )
    },
    ...(hasPublishing
      ? [
          {
            id: "publishing",
            label: t("publishing"),
            icon: Send,
            group: access,
            summary: summary.publishing(assistant.published),
            node: <PublishingSection assistant={assistant} />
          }
        ]
      : [])
  ];

  const test = (
    <Button asChild size="sm">
      <Link href={chatHref}>
        <Play className="size-4" />
        {t("test")}
      </Link>
    </Button>
  );
  const phone = useEditorPhoneIndex({
    section: "assistants",
    name: assistant.name,
    actions: (
      <AstryxButton
        href={chatHref}
        variant="secondary"
        icon={<Play aria-hidden="true" className="size-4" />}
        label={t("test")}
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
        header={<EditorHeader section="assistants" name={assistant.name} actions={test} />}
      />
    </SaveStatusProvider>
  );
}

export type { Assistant };
