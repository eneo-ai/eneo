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
import { useFormatter, useTranslations } from "use-intl";
import { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { CompanionLayout } from "@/components/composites/companion-layout";
import { SaveStatusProvider } from "@/components/composites/save-status";
import {
  SectionedSettings,
  type SectionedSettingsHandle,
  type SettingsSection
} from "@/components/composites/sectioned-settings";
import { useAppContext } from "@/components/providers/app-context";
import { Button as AstryxButton } from "@astryxdesign/core/Button";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/api/browser";
import { ResourceApiKeysSection } from "@/features/api-keys/resource-api-keys-section";
import { HelperPanel } from "@/features/helper/helper-panel";
import { ReferenceMenuButton } from "@/features/references/reference-menu";
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
import { AskHelperButton, AssistantHelperToggle, useAssistantHelper } from "./assistant-helper";
import { assistantHelperAvailabilityQueryOptions } from "./assistant-helper-api";
import { settingLabel } from "./assistant-helper-cards";
import { lockedAssistantModel } from "./effective-config";
import {
  SettingReferences,
  insertSettingMessage,
  useSettingReferenceMenu
} from "./setting-reference-pills";
import { settingMention, settingReferences, type AssistantSectionId } from "./setting-references";
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
 * (decision 11). While the helper is available, each section's "Fråga" and
 * "Hjälp mig välja modell" under the chat model put a reference to the
 * setting in its composer (never sending it), and a reference pill in the
 * chat shows its setting in the form.
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
  const format = useFormatter();
  const { settings } = useAppContext();
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
  // Ways into the helper from the form exist only where they can lead somewhere.
  const helperAvailable = availability?.available === true;
  const [helperOpen, setHelperOpen] = useState(false);
  // A prepared message for the composer, put there once the helper shows one.
  const pendingAsk = useRef<string | null>(null);
  const [askRequest, setAskRequest] = useState(0);
  // Set while the helper closes to show a setting: focus goes there, not to the toggle.
  const focusElsewhere = useRef(false);
  const changeHelperOpen = (open: boolean) => {
    if (!open) pendingAsk.current = null;
    setHelperOpen(open);
  };
  /** Opens the helper with `text` in its composer at the caret; nothing is sent. */
  const askHelper = (text: string) => {
    pendingAsk.current = text;
    setHelperOpen(true);
    setAskRequest((count) => count + 1);
  };
  const headerToggle = useRef<HTMLButtonElement>(null);
  const phoneToggle = useRef<HTMLButtonElement>(null);
  const settingsView = useRef<SectionedSettingsHandle>(null);
  const helperToggle = (compact: boolean) => (
    <AssistantHelperToggle
      ref={compact ? phoneToggle : headerToggle}
      availability={availability}
      open={helperOpen}
      onOpenChange={changeHelperOpen}
      compact={compact}
    />
  );
  /**
   * Where focus returns when the helper closes: the toggle on screen (the
   * header's, or a phone's bar's); nowhere when it closed to show a setting,
   * which takes the focus itself.
   */
  const returnFocus = () => {
    if (focusElsewhere.current) {
      focusElsewhere.current = false;
      return null;
    }
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

  // The model can be chosen here: by someone who may edit, where no policy sets it.
  const canChooseModel =
    permissions.includes("edit") &&
    lockedAssistantModel(space.completion_models, assistant.effective_config) === null;
  const askAboutModel =
    helperAvailable && canChooseModel
      ? () =>
          askHelper(
            t("helper_ask_model_question", {
              setting: settingMention({
                key: "completion_model",
                label: settingLabel("completion_model", t)
              })
            })
          )
      : undefined;

  const sections: (SettingsSection & { id: AssistantSectionId })[] = [
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
            id: "skills" as const,
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
      node: <AiSection assistant={assistant} draft={ai} onAskModel={askAboutModel} />
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
            id: "widget" as const,
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
            id: "publishing" as const,
            label: t("publishing"),
            icon: Send,
            group: access,
            summary: summary.publishing(assistant.published),
            node: <PublishingSection assistant={assistant} />
          }
        ]
      : [])
  ];

  // What the helper chat can refer to: the sections in this list and the settings they show.
  const referenceList = settingReferences({
    sections,
    assistant,
    model: ai.toolModel,
    kwargsModel: ai.model,
    kwargs: ai.kwargs,
    fileReferences: settings.file_references_enabled === true,
    t,
    format
  });
  const {
    references: chatReferences,
    composer,
    byKey: referenceMap
  } = useSettingReferenceMenu(referenceList);
  const helper = useAssistantHelper({
    assistant,
    availability,
    references: chatReferences,
    footerActions: composer ? (
      <ReferenceMenuButton label={t("helper_reference_button")} input={composer} />
    ) : null
  });

  // A prepared message goes in once the helper is open and its composer is on screen.
  useEffect(() => {
    const text = pendingAsk.current;
    if (text === null || !helperOpen || !composer) return;
    pendingAsk.current = null;
    insertSettingMessage(composer, text, referenceMap);
  }, [askRequest, helperOpen, composer, referenceMap]);

  /**
   * A pill pressed in the chat: the form shows its setting and focus moves
   * to it. Where the helper covers the form (a narrow row, a phone), the
   * helper closes first so the person sees it.
   */
  const showSetting = (key: string) => {
    const reference = referenceMap.get(key);
    if (!reference) return;
    if (helperOpen && document.getElementById(reference.section)?.closest("[inert]")) {
      focusElsewhere.current = true;
      flushSync(() => changeHelperOpen(false));
    }
    settingsView.current?.show({ section: reference.section, control: reference.control });
  };

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
    <SettingReferences references={referenceMap} show={showSetting}>
      <CompanionLayout
        open={helperOpen}
        label={t("helper_heading")}
        resizeLabel={t("helper_resize")}
        widthStorageKey="eneo:assistant-helper-width"
        returnFocus={returnFocus}
        aside={(presentation) => (
          <HelperPanel
            adapter={helper}
            close={{
              label: presentation === "phone" ? t("helper_back") : t("helper_close"),
              onClose: () => changeHelperOpen(false),
              asBack: presentation === "phone"
            }}
          />
        )}
      >
        <SectionedSettings
          handleRef={settingsView}
          navigationLabel={t("editor_sections_label")}
          sections={sections}
          phone={phone}
          sectionAction={
            helperAvailable
              ? (section) => (
                  <AskHelperButton
                    section={section.label}
                    onAsk={() => {
                      const reference = referenceMap.get(`section:${section.id}`);
                      if (reference) askHelper(settingMention(reference));
                    }}
                  />
                )
              : undefined
          }
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
    </SettingReferences>
  );
}

export type { Assistant };
