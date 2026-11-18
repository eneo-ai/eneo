import { useQuery, useSuspenseQuery } from "@tanstack/react-query";
import {
  BookOpen,
  BookOpenCheck,
  Globe,
  KeyRound,
  MessageSquare,
  MessageSquareCode,
  Paperclip,
  Play,
  Plug,
  Send,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles
} from "lucide-react";
import Link from "@/lib/link";
import { useTranslations } from "use-intl";
import { useRef, useState } from "react";
import { CompanionLayout } from "@/components/composites/companion-layout";
import { SaveStatusProvider } from "@/components/composites/save-status";
import {
  SectionedSettings,
  type SettingsSection
} from "@/components/composites/sectioned-settings";
import { Button as AstryxButton } from "@astryxdesign/core/Button";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/api/browser";
import { ResourceApiKeysSection } from "@/features/api-keys/resource-api-keys-section";
import { HelperPanel } from "@/features/helper/helper-panel";
import { editorSummaries } from "@/features/spaces/editor-summaries";
import {
  EditorHeader,
  useCreatedAnnouncement,
  useEditorPhoneIndex
} from "@/features/spaces/editor-header";
import { useJustCreated } from "@/features/spaces/just-created";
import { useSpace } from "@/features/spaces/use-space";
import { AssistantWidgetSection } from "@/features/widget/admin/assistant-widget-section";
import { SkillBindingsSection } from "@/features/skills/skill-bindings-section";
import { useCanAttachSkills } from "@/features/skills/use-can-attach-skills";
import { chatPartnerHref } from "../assistants";
import { AiSection } from "./ai-section";
import { AssistantHelperToggle, useAssistantHelper } from "./assistant-helper";
import { assistantHelperAvailabilityQueryOptions } from "./assistant-helper-api";
import { useAssistantAiDraft } from "./use-assistant-ai-draft";
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
 *
 * "Hjälpassistent" in the header (and in a phone's bar) opens the helper chat
 * beside the settings, or over them where the row has no room; it follows
 * the helper's availability. The personal chat's own assistant has no helper
 * (decision 11).
 */
export function AssistantEditor({ assistantId }: { assistantId: string }) {
  return (
    <SaveStatusProvider>
      <AssistantEditorContent assistantId={assistantId} />
    </SaveStatusProvider>
  );
}

function AssistantEditorContent({ assistantId }: { assistantId: string }) {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const canAttachSkills = useCanAttachSkills();
  const { data: assistant } = useSuspenseQuery(assistantQueryOptions(browserApi, assistantId));
  const update = useUpdateAssistant(assistantId);
  const ai = useAssistantAiDraft(assistant);
  const created = useJustCreated("assistant", assistantId);
  useCreatedAnnouncement(created, t("assistant_created_announcement"));

  const chatHref = chatPartnerHref(routeId, { ...assistant, type: "assistant" as const });

  const personalDefault = space.personal && space.default_assistant?.id === assistant.id;
  const availabilityQuery = useQuery({
    ...assistantHelperAvailabilityQueryOptions(browserApi, assistantId),
    enabled: !personalDefault
  });
  const availability = personalDefault ? undefined : availabilityQuery.data;
  const helper = useAssistantHelper({ assistant, availability });
  const [helperOpen, setHelperOpen] = useState(false);
  const headerToggle = useRef<HTMLButtonElement>(null);
  const phoneToggle = useRef<HTMLButtonElement>(null);
  const helperToggle = (compact: boolean) => (
    <AssistantHelperToggle
      ref={compact ? phoneToggle : headerToggle}
      availability={availability}
      open={helperOpen}
      onOpenChange={setHelperOpen}
      compact={compact}
    />
  );
  /** The toggle on screen (the header's, or a phone's bar's), for focus to return to. */
  const shownToggle = () => {
    const toggles = [headerToggle.current, phoneToggle.current];
    return (
      toggles.find((toggle) => toggle?.isConnected && toggle.getClientRects().length > 0) ??
      toggles.find((toggle) => toggle?.isConnected) ??
      null
    );
  };

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
      node: (
        <InstructionsSection
          assistant={assistant}
          contextModel={ai.effectiveModel}
          modelConfirmed={ai.confirmed}
        />
      )
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
      node: (
        <KnowledgeSection
          assistant={assistant}
          modelSupportsTools={ai.toolModel?.supports_tool_calling === true}
        />
      )
    },
    ...(canAttachSkills && (!space.personal || space.default_assistant?.id !== assistant.id)
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
    {
      id: "mcp",
      label: t("mcp_servers"),
      icon: Plug,
      group: content,
      summary: summary.chosen(assistant.mcp_servers?.length ?? 0),
      node: <McpSection assistant={assistant} />
    },
    {
      id: "attachments",
      label: t("attachments"),
      icon: Paperclip,
      group: content,
      summary: summary.files(assistant.attachments.length),
      node: <AttachmentsSection assistant={assistant} model={ai.toolModel} />
    },
    {
      id: "ai",
      label: t("ai_settings"),
      icon: Sparkles,
      group: model,
      summary: summary.model(assistant.completion_model),
      node: <AiSection assistant={assistant} draft={ai} />
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
    ...(permissions.includes("edit")
      ? [
          {
            id: "widget",
            label: t("widget_admin_title"),
            icon: MessageSquareCode,
            group: access,
            node: <AssistantWidgetSection assistantId={assistant.id} />
          }
        ]
      : []),
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
      <>
        {helperToggle(true)}
        <AstryxButton
          href={chatHref}
          variant="secondary"
          icon={<Play aria-hidden="true" className="size-4" />}
          label={t("test")}
        />
      </>
    ),
    created
  });

  return (
    <CompanionLayout
      open={helperOpen}
      label={t("helper_heading")}
      resizeLabel={t("helper_resize")}
      widthStorageKey="eneo:assistant-helper-width"
      returnFocus={shownToggle}
      aside={(presentation) => (
        <HelperPanel
          adapter={helper}
          close={{
            label: presentation === "phone" ? t("helper_back") : t("helper_close"),
            onClose: () => setHelperOpen(false),
            asBack: presentation === "phone"
          }}
        />
      )}
    >
      <SectionedSettings
        navigationLabel={t("editor_sections_label")}
        sections={sections}
        phone={phone}
        header={
          <EditorHeader
            section="assistants"
            name={assistant.name}
            actions={
              <>
                {helperToggle(false)}
                {test}
              </>
            }
          />
        }
      />
    </CompanionLayout>
  );
}

export type { Assistant };
