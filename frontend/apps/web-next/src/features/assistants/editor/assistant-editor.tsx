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
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/api/browser";
import { ResourceApiKeysSection } from "@/features/api-keys/resource-api-keys-section";
import { EditorHeader, useCreatedAnnouncement } from "@/features/spaces/editor-header";
import { useJustCreated } from "@/features/spaces/just-created";
import { useSpace } from "@/features/spaces/use-space";
import { SkillBindingsSection } from "@/features/skills/skill-bindings-section";
import { chatPartnerHref } from "../assistants";
import { AiSection } from "./ai-section";
import { GeneralSection } from "./general-section";
import { AttachmentsSection } from "./attachments-section";
import { CapabilitiesSection } from "./capabilities-section";
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

  const sections: SettingsSection[] = [
    {
      id: "general",
      label: t("general"),
      icon: SlidersHorizontal,
      node: <GeneralSection assistant={assistant} focusName={created} />
    },
    {
      id: "instructions",
      label: t("instructions"),
      icon: MessageSquare,
      node: <InstructionsSection assistant={assistant} />
    },
    {
      id: "knowledge",
      label: t("knowledge"),
      icon: BookOpen,
      node: <KnowledgeSection assistant={assistant} />
    },
    ...(can("read", "skill") && (!space.personal || space.default_assistant?.id !== assistant.id)
      ? [
          {
            id: "skills",
            label: t("skills"),
            icon: BookOpenCheck,
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
            node: <McpSection assistant={assistant} />
          }
        ]
      : []),
    {
      id: "capabilities",
      label: t("capabilities"),
      icon: Globe,
      node: <CapabilitiesSection assistant={assistant} />
    },
    {
      id: "attachments",
      label: t("attachments"),
      icon: Paperclip,
      node: <AttachmentsSection assistant={assistant} />
    },
    {
      id: "ai",
      label: t("ai_settings"),
      icon: Sparkles,
      node: <AiSection assistant={assistant} />
    },
    {
      id: "security",
      label: t("security_and_privacy"),
      icon: ShieldCheck,
      node: <SecuritySection assistant={assistant} />
    },
    {
      id: "api-keys",
      label: t("api_keys"),
      icon: KeyRound,
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
            node: <PublishingSection assistant={assistant} />
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
            section="assistants"
            name={assistant.name}
            actions={
              <Button asChild size="sm">
                <Link href={chatHref}>
                  <Play className="size-4" />
                  {t("test")}
                </Link>
              </Button>
            }
          />
        }
      />
    </SaveStatusProvider>
  );
}

export type { Assistant };
