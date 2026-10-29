"use client";

import { AlertDialog } from "@astryxdesign/core/AlertDialog";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Selector } from "@astryxdesign/core/Selector";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { ExternalLink, FileText, Palette, Rocket, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { Switch } from "@/components/astryx/switch";
import { TextInput } from "@/components/astryx/text-input";
import { SettingsGroup } from "@/components/composites/settings-rows";
import type { Schema } from "@/lib/api/models";
import type { Widget } from "./autosave";
import { blockerLabel } from "./blockers";
import { toastWidgetError } from "./errors";
import { widgetApi, type WidgetPolicy, type WidgetTemplate } from "./queries";
import type { LoaderRelease } from "./snippet";
import { TemplatePicker } from "./template-picker";
import { isGroupLocked, lockedTextFields } from "./template-locks";
import { collapseWhitespace } from "./text";
import { DraftWrapper, useTextDraft } from "./use-text-draft";
import { useUrlTab } from "./use-url-tab";
import { useWidgetAutosave } from "./use-widget-autosave";
import { WidgetLiveTest } from "./widget-live-test";
import { WidgetPersonaFields } from "./widget-persona-fields";
import { WidgetPreview } from "./widget-preview";
import { WidgetRulesFields } from "./widget-rules-fields";
import { WidgetSnippet } from "./widget-snippet";
import { WidgetStatusBar } from "./widget-status-bar";
import { WidgetTextsFields } from "./widget-texts-fields";
import { WidgetThemeFields } from "./widget-theme-fields";
import { WidgetUsage } from "./widget-usage";

type Assistant = Schema<"AssistantPublic">;

const TABS = ["content", "appearance", "rules", "publish"] as const;
type TabId = (typeof TABS)[number];

/** What an active widget exposes besides knowledge, as the backend serves visitors. */
const VISITOR_CAPABILITIES: ReadonlySet<string> = new Set(["web_search"]);

/** What linking copies from the template's release onto the widget. */
const RELEASE_GROUPS = ["texts", "theme", "language"];

/**
 * The "Webbwidget" page body. Status and lifecycle on top; then four tabs in
 * the order an editor works: what the chat says (Innehåll), how it looks
 * (Utseende), where and how much it may run (Regler) and getting it onto the
 * site (Publicera). The live preview sits beside the first two tabs.
 */
export function WidgetEditor({
  widget,
  assistant,
  isAdmin,
  policy,
  release,
  appOrigin,
  templates: allTemplates,
  onArchived
}: {
  widget: Widget;
  assistant: Assistant;
  isAdmin: boolean;
  policy: WidgetPolicy | null;
  release: LoaderRelease | null;
  appOrigin: string;
  templates: WidgetTemplate[];
  /** An archived widget cannot be edited, so the page takes the editor away. */
  onArchived: () => void;
}) {
  const t = useTranslations();
  const ids = useId();
  // Widgets follow a template's published release, so drafts are not offered.
  const templates = allTemplates.filter((template) => template.published_at != null);
  const { autosave, state } = useWidgetAutosave(widget);
  const current = state.widget;
  const [tab, setTab] = useUrlTab(TABS, "content");

  // A blank name is never sent: the API would refuse it and hold every
  // later edit back with it.
  const name = useTextDraft(current.name);
  const nameProblem = !collapseWhitespace(name.text)
    ? t("widget_admin_name_required")
    : state.refusals["name"];
  const refusalsIn = (group: string) =>
    Object.fromEntries(
      Object.entries(state.refusals)
        .filter(([path]) => path.startsWith(`${group}.`))
        .map(([path, message]) => [path.slice(group.length + 1), message])
    );
  const textErrors = refusalsIn("texts");
  const personaErrors = refusalsIn("persona");
  // The theme fields check what they send, so a refusal here is rare and
  // shown once for the whole appearance.
  const appearanceErrors = [
    ...new Set([state.refusals["theme"], ...Object.values(refusalsIn("theme"))].filter(Boolean))
  ] as string[];

  // Pending edits are saved first so pause and archive never race the
  // autosave; a save that fails does not stop the kill switch.
  const lifecycle = (action: (id: string) => Promise<Widget>) => async () => {
    await autosave.flush();
    autosave.replace(await action(widget.id));
  };

  // Linking a template overwrites texts and appearance, so it asks first;
  // detaching hands every part back to the editor, so it asks too. Reapplying
  // is linking again: the release is copied whole, unlocked parts included.
  const [templateChoice, setTemplateChoice] = useState("");
  const [confirm, setConfirm] = useState<"apply" | "reapply" | "detach" | null>(null);
  const [applying, setApplying] = useState(false);
  const chosenTemplate = templates.find((template) => template.id === templateChoice) ?? null;

  // The template the widget follows and what it freezes in this editor. The
  // server refuses locked changes too; the UI just stops them being attempted.
  const link = current.template ?? null;
  const lockedTexts = lockedTextFields(link);
  const languageLocked = isGroupLocked(link, "language");
  const appearanceLocked = isGroupLocked(link, "appearance");
  const personaLocked = isGroupLocked(link, "persona");
  const lockHint = link ? t("widget_admin_template_locked_hint", { name: link.name }) : "";
  const groupLabels: Record<string, string> = {
    appearance: t("widget_admin_template_lock_appearance"),
    language: t("widget_admin_template_lock_language"),
    legal_texts: t("widget_admin_template_lock_legal_texts"),
    persona: t("widget_admin_template_lock_persona"),
    wording: t("widget_admin_template_lock_wording")
  };
  const lockedParts = (link?.locked_groups ?? [])
    .map((group) => groupLabels[group] ?? group)
    .join(", ");

  async function withTemplate(action: () => Promise<Widget>, replaced: string[]) {
    setApplying(true);
    try {
      await autosave.flush();
      if (autosave.hasPending) return false;
      const updated = await action();
      // Refused edits of the groups the release replaced are moot; any other
      // refused edit stays on screen, held with its reason.
      autosave.discardRefused(replaced);
      autosave.replace(updated);
      return true;
    } catch (error) {
      toastWidgetError(error, t);
      return false;
    } finally {
      setApplying(false);
    }
  }

  async function confirmed() {
    if (confirm === "apply" && chosenTemplate) {
      if (
        await withTemplate(
          () => widgetApi.linkTemplate(widget.id, chosenTemplate.id, current.revision),
          RELEASE_GROUPS
        )
      ) {
        setConfirm(null);
        setTemplateChoice("");
      }
    } else if (confirm === "reapply" && link) {
      if (
        await withTemplate(
          () => widgetApi.linkTemplate(widget.id, link.id, current.revision),
          RELEASE_GROUPS
        )
      ) {
        setConfirm(null);
      }
    } else if (confirm === "detach") {
      if (await withTemplate(() => widgetApi.detachTemplate(widget.id, current.revision), [])) {
        setConfirm(null);
      }
    }
  }

  const languageOptions = [
    { value: "auto", label: t("widget_admin_language_auto") },
    { value: "sv", label: t("widget_admin_language_sv") },
    { value: "en", label: t("widget_admin_language_en") }
  ];

  const blockers = current.activation_blockers ?? [];
  // The assistant's general MCP servers as configured, and web search only
  // through an external provider (VISITOR_CAPABILITY_PURPOSES in
  // assistant_service.py). Image generation never.
  const visitorServers = (assistant.mcp_servers ?? []).filter(
    (server) => server.purpose === "general" && server.is_enabled
  );
  const visitorCapabilities = (assistant.enabled_capabilities ?? [])
    .filter((purpose) => VISITOR_CAPABILITIES.has(purpose))
    // The one visitor capability has the same name everywhere in the app.
    .map((purpose) => (purpose === "web_search" ? t("web_search") : purpose));
  const showPreview = tab === "content" || tab === "appearance";

  const tabId = (value: TabId) => `${ids}-tab-${value}`;
  const panelId = (value: TabId) => `${ids}-panel-${value}`;
  const panel = (value: TabId, children: React.ReactNode) => (
    <div
      role="tabpanel"
      id={panelId(value)}
      aria-labelledby={tabId(value)}
      hidden={tab !== value}
      className="flex flex-col gap-6"
    >
      {children}
    </div>
  );

  const confirmTexts =
    confirm === "apply"
      ? {
          title: t("widget_admin_template_apply_confirm_title"),
          description: t("widget_admin_template_apply_confirm_description", {
            name: chosenTemplate?.name ?? ""
          }),
          action: t("widget_admin_template_apply")
        }
      : confirm === "reapply"
        ? {
            title: t("widget_admin_template_reapply_confirm_title"),
            description: t("widget_admin_template_reapply_confirm_description", {
              name: link?.name ?? ""
            }),
            action: t("widget_admin_template_reapply")
          }
        : {
            title: t("widget_admin_template_detach_confirm_title"),
            description: t("widget_admin_template_detach_confirm_description", {
              name: link?.name ?? ""
            }),
            action: t("widget_admin_template_detach")
          };

  return (
    <div className="flex flex-col gap-6">
      <WidgetStatusBar
        autosave={autosave}
        state={state}
        isAdmin={isAdmin}
        onReload={async () => autosave.reload(await widgetApi.get(widget.id))}
        onActivate={lifecycle(widgetApi.activate)}
        onPause={lifecycle(widgetApi.pause)}
        onArchive={async () => {
          await lifecycle(widgetApi.archive)();
          onArchived();
        }}
      />

      <TabList
        role="tablist"
        aria-label={t("widget_admin_title")}
        value={tab}
        onChange={(next) => setTab(next as TabId)}
        hasDivider
      >
        <Tab
          id={tabId("content")}
          value="content"
          label={t("widget_admin_tab_content")}
          icon={<FileText aria-hidden="true" className="size-4" />}
          panelId={panelId("content")}
        />
        <Tab
          id={tabId("appearance")}
          value="appearance"
          label={t("widget_admin_tab_appearance")}
          icon={<Palette aria-hidden="true" className="size-4" />}
          panelId={panelId("appearance")}
        />
        <Tab
          id={tabId("rules")}
          value="rules"
          label={t("widget_admin_tab_rules")}
          icon={<SlidersHorizontal aria-hidden="true" className="size-4" />}
          panelId={panelId("rules")}
        />
        <Tab
          id={tabId("publish")}
          value="publish"
          label={t("widget_admin_tab_publish")}
          icon={<Rocket aria-hidden="true" className="size-4" />}
          panelId={panelId("publish")}
          endContent={
            blockers.length > 0 ? (
              <Badge
                variant="error"
                label={
                  blockers.length === 1
                    ? t("widget_admin_tab_issues_one")
                    : t("widget_admin_tab_issues", { count: blockers.length })
                }
              />
            ) : undefined
          }
        />
      </TabList>

      {/* The preview column exists only while the preview is shown; the
          rules and publish tabs take the whole width. */}
      <div
        className={
          showPreview ? "grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(380px,460px)]" : "grid gap-6"
        }
      >
        <div className="flex min-w-0 flex-col gap-6">
          {panel(
            "content",
            <>
              <SettingsGroup
                title={t("general")}
                description={t("widget_admin_content_description")}
              >
                <div className="grid gap-6 sm:grid-cols-2">
                  <DraftWrapper onFocus={name.onFocus} onBlur={name.onBlur}>
                    <TextInput
                      label={t("name")}
                      description={t("widget_admin_name_description")}
                      value={name.text}
                      isRequired
                      onChange={(value) => {
                        const next = value.slice(0, 100);
                        name.setText(next);
                        if (collapseWhitespace(next)) autosave.patch({ name: next });
                      }}
                      status={nameProblem ? { type: "error", message: nameProblem } : undefined}
                      width="100%"
                    />
                  </DraftWrapper>
                  <Selector
                    label={t("widget_admin_language")}
                    description={t("widget_admin_language_description")}
                    options={languageOptions}
                    value={current.language ?? "auto"}
                    isDisabled={languageLocked}
                    disabledMessage={languageLocked ? lockHint : undefined}
                    onChange={(value) =>
                      autosave.patch({ language: value as NonNullable<Widget["language"]> })
                    }
                    width="100%"
                  />
                </div>
                <Switch
                  label={t("widget_admin_show_sources")}
                  description={t("widget_admin_show_sources_description")}
                  value={current.show_sources ?? true}
                  labelPosition="start"
                  labelSpacing="spread"
                  width="100%"
                  onChange={(checked) => autosave.patch({ show_sources: checked })}
                />
                <Switch
                  label={t("widget_admin_show_tool_activity")}
                  description={t("widget_admin_show_tool_activity_description")}
                  value={current.show_tool_activity ?? true}
                  labelPosition="start"
                  labelSpacing="spread"
                  width="100%"
                  onChange={(checked) => autosave.patch({ show_tool_activity: checked })}
                />
              </SettingsGroup>

              <SettingsGroup
                title={t("widget_admin_texts")}
                description={t("widget_admin_texts_description")}
              >
                {state.refusals["texts"] && (
                  <p className="text-ax-red text-sm">{state.refusals["texts"]}</p>
                )}
                <WidgetTextsFields
                  texts={current.texts}
                  lockedFields={lockedTexts}
                  lockHint={lockHint}
                  errors={textErrors}
                  subtitleRequired={
                    current.status === "active"
                      ? t("widget_admin_blocker_subtitle_empty")
                      : undefined
                  }
                  onQuestionsHeld={(held) => autosave.markDraft("texts.suggested_questions", held)}
                  onChange={(change) =>
                    autosave.patch({ texts: { ...autosave.widget.texts, ...change } })
                  }
                />
              </SettingsGroup>

              <SettingsGroup
                title={t("widget_admin_persona")}
                description={t("widget_admin_persona_description")}
              >
                {state.refusals["persona"] && (
                  <p className="text-ax-red text-sm">{state.refusals["persona"]}</p>
                )}
                <WidgetPersonaFields
                  persona={current.persona ?? {}}
                  chatTitle={current.texts.title ?? ""}
                  assistantIconId={assistant.icon_id ?? null}
                  locked={personaLocked}
                  lockHint={lockHint}
                  errors={personaErrors}
                  onChange={(persona) => autosave.patch({ persona })}
                />
              </SettingsGroup>
            </>
          )}

          {panel(
            "appearance",
            <>
              {link ? (
                <SettingsGroup
                  title={t("widget_admin_template_linked_title", { name: link.name })}
                  description={t("widget_admin_template_linked_description")}
                >
                  <p className="text-sm">
                    {lockedParts
                      ? t("widget_admin_template_locked_parts", { parts: lockedParts })
                      : t("widget_admin_template_locks_nothing")}
                  </p>
                  <div className="flex flex-wrap items-center gap-2">
                    {isAdmin && (
                      <Button
                        variant="ghost"
                        label={t("widget_admin_template_open")}
                        href={`/admin/widgets/templates/${link.id}`}
                        as={Link}
                        endContent={<ExternalLink aria-hidden="true" className="size-4" />}
                      />
                    )}
                    {current.status !== "archived" && (
                      <>
                        <Button
                          label={t("widget_admin_template_reapply")}
                          onClick={() => setConfirm("reapply")}
                        />
                        <Button
                          label={t("widget_admin_template_detach")}
                          onClick={() => setConfirm("detach")}
                        />
                      </>
                    )}
                  </div>
                </SettingsGroup>
              ) : templates.length > 0 && current.status !== "archived" ? (
                <SettingsGroup
                  title={t("widget_admin_template_pick_title")}
                  description={t("widget_admin_template_apply_description")}
                >
                  <TemplatePicker
                    templates={templates}
                    value={templateChoice}
                    onChange={setTemplateChoice}
                    legend={t("widget_admin_template_pick_title")}
                  />
                  <div>
                    <Button
                      label={t("widget_admin_template_apply")}
                      isDisabled={!chosenTemplate}
                      onClick={() => setConfirm("apply")}
                    />
                  </div>
                </SettingsGroup>
              ) : null}

              <SettingsGroup
                title={t("widget_admin_appearance")}
                description={t("widget_admin_appearance_description")}
              >
                {appearanceErrors.length > 0 && (
                  <div className="flex flex-col gap-1">
                    {appearanceErrors.map((message) => (
                      <p key={message} className="text-ax-red text-sm">
                        {message}
                      </p>
                    ))}
                  </div>
                )}
                <WidgetThemeFields
                  theme={current.theme}
                  locked={appearanceLocked}
                  lockHint={lockHint}
                  onChange={(change) =>
                    autosave.patch({ theme: { ...autosave.widget.theme, ...change } })
                  }
                />
              </SettingsGroup>
            </>
          )}

          {panel("rules", <WidgetRulesFields autosave={autosave} state={state} policy={policy} />)}

          {panel(
            "publish",
            <>
              <SettingsGroup
                title={t("widget_admin_publish_checklist")}
                description={
                  assistant.published
                    ? t("widget_admin_publish_checklist_description")
                    : t("widget_admin_assistant_unpublished_description")
                }
              >
                {blockers.length === 0 ? (
                  <p className="text-ax-green text-sm">
                    {current.status === "active"
                      ? t("widget_admin_publish_live")
                      : t("widget_admin_publish_ready")}
                  </p>
                ) : (
                  <ul className="list-disc pl-5 text-sm">
                    {blockers.map((blocker) => (
                      <li key={blocker}>{blockerLabel(blocker, t)}</li>
                    ))}
                  </ul>
                )}
                <section aria-labelledby={`${ids}-visitor-access`} className="flex flex-col gap-1">
                  <h3 id={`${ids}-visitor-access`} className="text-sm font-medium">
                    {t("widget_admin_visitor_access")}
                  </h3>
                  <p className="text-ax-text-secondary text-sm">
                    {t("widget_admin_visitor_access_description")}
                  </p>
                  <ul className="mt-1 list-disc pl-5 text-sm">
                    <li>{t("widget_admin_visitor_access_knowledge")}</li>
                    {visitorServers.map((server) => (
                      <li key={server.id}>{server.name}</li>
                    ))}
                    {visitorCapabilities.map((capability) => (
                      <li key={capability}>
                        {t("widget_admin_visitor_access_capability", { name: capability })}
                      </li>
                    ))}
                    {visitorServers.length + visitorCapabilities.length > 0 &&
                      !(current.show_tool_activity ?? true) && (
                        <li className="text-ax-text-secondary">
                          {t("widget_admin_visitor_access_hidden")}
                        </li>
                      )}
                  </ul>
                  <p className="text-ax-text-secondary text-sm">
                    {t("widget_admin_visitor_access_never")}
                  </p>
                </section>
              </SettingsGroup>
              <WidgetSnippet widget={current} release={release} origin={appOrigin} />
              <WidgetLiveTest widget={current} release={release} />
              <WidgetUsage widget={current} visible={tab === "publish"} />
            </>
          )}
        </div>

        {/* Kept mounted across tabs so switching back does not mint a new
            preview token and reload the frame. */}
        <aside className="min-w-0 self-start xl:sticky xl:top-24" hidden={!showPreview}>
          <WidgetPreview widget={current} />
        </aside>
      </div>

      <AlertDialog
        isOpen={confirm !== null}
        onOpenChange={(open) => {
          if (!open && !applying) setConfirm(null);
        }}
        title={confirmTexts.title}
        description={confirmTexts.description}
        actionLabel={confirmTexts.action}
        actionVariant="primary"
        cancelLabel={t("cancel")}
        isActionLoading={applying}
        onAction={() => void confirmed()}
      />
    </div>
  );
}
