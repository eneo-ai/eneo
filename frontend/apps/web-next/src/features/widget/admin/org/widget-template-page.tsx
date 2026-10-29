"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { Selector } from "@astryxdesign/core/Selector";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { TextArea } from "@astryxdesign/core/TextArea";
import { useQuery } from "@tanstack/react-query";
import { FileText, Palette } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useId, useState } from "react";
import { Switch } from "@/components/astryx/switch";
import { TextInput } from "@/components/astryx/text-input";
import { PageHeader } from "@/components/composites/page-header";
import { SaveStatusIndicator, SaveStatusProvider } from "@/components/composites/save-status";
import { SettingsGroup } from "@/components/composites/settings-rows";
import { browserApi } from "@/lib/api/browser";
import { WidgetTemplateAutosave, type WidgetTemplate } from "../autosave";
import { toastWidgetError, widgetFieldErrors } from "../errors";
import { LOCK_GROUPS, publicationSummary, type WidgetTemplateLockGroup } from "../template-locks";
import { collapseWhitespace } from "../text";
import { DraftWrapper, useTextDraft } from "../use-text-draft";
import { useAutosave } from "../use-widget-autosave";
import { WidgetPersonaFields } from "../widget-persona-fields";
import { WidgetTextsFields } from "../widget-texts-fields";
import { WidgetThemeFields } from "../widget-theme-fields";
import { widgetTemplateApi, widgetTemplateQueryOptions } from "./queries";
import { WidgetMockPreview } from "./widget-mock-preview";

type TabId = "content" | "appearance";

/** The template page: its editor once the template is loaded. */
export function WidgetTemplatePage({ templateId }: { templateId: string }) {
  const t = useTranslations();
  const template = useQuery(widgetTemplateQueryOptions(browserApi, templateId));
  if (!template.data) {
    return (
      <p className="text-ax-text-secondary text-sm">
        {template.isError ? t("widget_admin_template_failed") : t("loading")}
      </p>
    );
  }
  return <TemplateEditor key={template.data.id} template={template.data} />;
}

/**
 * Edit one widget template: the house style editors copy onto new widgets.
 * Autosaved like the widget page; a static preview shows the result. Saving
 * edits the draft; publishing is the deliberate step that reaches the
 * widgets, and with followers it asks first, since their values change.
 */
function TemplateEditor({ template: initial }: { template: WidgetTemplate }) {
  const t = useTranslations();
  const locale = useLocale();
  const ids = useId();
  const { autosave, state } = useAutosave(
    () =>
      new WidgetTemplateAutosave(
        initial,
        async (update) => {
          try {
            return await widgetTemplateApi.update(initial.id, update);
          } catch (error) {
            toastWidgetError(error, t);
            throw error;
          }
        },
        { fieldErrors: (error) => widgetFieldErrors(error, t) }
      ),
    "widget-template"
  );
  const template = state.widget;

  const name = useTextDraft(template.name);
  const description = useTextDraft(template.description ?? "", (text) => text);
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
  // The legal-texts lock needs a subtitle to enforce; the API refuses the
  // save otherwise, so the switch waits until there is one.
  const hasSubtitle = (template.texts.subtitle ?? "").trim().length > 0;
  const legalLocked = template.locked_groups.includes("legal_texts");

  const lockLabels: Record<WidgetTemplateLockGroup, { label: string; description: string }> = {
    appearance: {
      label: t("widget_admin_template_lock_appearance"),
      description: t("widget_admin_template_lock_appearance_description")
    },
    language: {
      label: t("widget_admin_template_lock_language"),
      description: t("widget_admin_template_lock_language_description")
    },
    legal_texts: {
      label: t("widget_admin_template_lock_legal_texts"),
      description: t("widget_admin_template_lock_legal_texts_description")
    },
    persona: {
      label: t("widget_admin_template_lock_persona"),
      description: t("widget_admin_template_lock_persona_description")
    },
    wording: {
      label: t("widget_admin_template_lock_wording"),
      description: t("widget_admin_template_lock_wording_description")
    }
  };
  const linkedLabel =
    template.linked_widgets === 0
      ? t("widget_admin_template_linked_none")
      : template.linked_widgets === 1
        ? t("widget_admin_template_linked_count_one")
        : t("widget_admin_template_linked_count", { count: String(template.linked_widgets) });

  function setLock(group: WidgetTemplateLockGroup, locked: boolean) {
    autosave.patch({
      locked_groups: LOCK_GROUPS.filter((candidate) =>
        candidate === group ? locked : template.locked_groups.includes(candidate)
      )
    });
  }

  const dateFormat = new Intl.DateTimeFormat(locale === "sv" ? "sv-SE" : "en-US", {
    dateStyle: "medium",
    timeStyle: "short"
  });
  const publicationLabel =
    template.published_at == null
      ? t("widget_admin_template_unpublished")
      : template.has_unpublished_changes
        ? t("widget_admin_template_unpublished_changes")
        : t("widget_admin_template_published_at", {
            date: dateFormat.format(new Date(template.published_at))
          });

  // The dialog names what the followers lose or regain, so an admin is not
  // confirming a count but a change.
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const summary = publicationSummary(template);
  const groupNames = (groups: WidgetTemplateLockGroup[]) =>
    groups.map((group) => lockLabels[group].label).join(", ");
  const changesNothing =
    summary.written.length === 0 &&
    summary.newlyLocked.length === 0 &&
    summary.released.length === 0;

  async function publish() {
    if (publishing) return;
    setPublishing(true);
    try {
      await autosave.flush();
      if (autosave.hasPending) return;
      autosave.replace(await widgetTemplateApi.publish(initial.id));
      setConfirmOpen(false);
    } catch (error) {
      toastWidgetError(error, t);
    } finally {
      setPublishing(false);
    }
  }
  function requestPublish() {
    if (template.linked_widgets > 0) setConfirmOpen(true);
    else void publish();
  }

  const [tab, setTab] = useState<TabId>("content");
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

  const languageOptions = [
    { value: "auto", label: t("widget_admin_language_auto") },
    { value: "sv", label: t("widget_admin_language_sv") },
    { value: "en", label: t("widget_admin_language_en") }
  ];

  return (
    <SaveStatusProvider>
      <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-6">
        <PageHeader
          title={template.name}
          breadcrumbs={[
            { label: t("shell_administration"), href: "/admin" },
            { label: t("widget_admin_nav"), href: "/admin/widgets?tab=templates" },
            { label: template.name, current: true }
          ]}
          actions={
            <div className="flex flex-wrap items-center gap-3">
              <SaveStatusIndicator />
              <Badge
                variant={template.has_unpublished_changes ? "warning" : "neutral"}
                label={publicationLabel}
              />
              {/* The visible badge explains the state; a tooltip on a disabled button would not. */}
              <Button
                variant="primary"
                label={t("widget_admin_template_publish")}
                isDisabled={!template.has_unpublished_changes}
                isLoading={publishing && !confirmOpen}
                isInterruptible
                clickAction={requestPublish}
              />
            </div>
          }
        />

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(380px,460px)]">
          <div className="flex min-w-0 flex-col gap-6">
            <SettingsGroup
              title={t("widget_admin_template_details")}
              description={t("widget_admin_template_name_description")}
              headerEnd={
                <Badge
                  variant={template.linked_widgets > 0 ? "info" : "neutral"}
                  label={linkedLabel}
                />
              }
            >
              <p className="text-ax-text-secondary text-sm">
                {template.published_at == null
                  ? t("widget_admin_template_not_published_help")
                  : t("widget_admin_template_publish_description")}
              </p>
              <div className="grid gap-6 sm:grid-cols-2">
                <DraftWrapper onFocus={name.onFocus} onBlur={name.onBlur}>
                  <TextInput
                    label={t("name")}
                    value={name.text}
                    isRequired
                    status={nameProblem ? { type: "error", message: nameProblem } : undefined}
                    width="100%"
                    onChange={(typed) => {
                      const value = typed.slice(0, 100);
                      name.setText(value);
                      if (collapseWhitespace(value)) autosave.patch({ name: value });
                    }}
                  />
                </DraftWrapper>
                <Selector
                  label={t("widget_admin_language")}
                  options={languageOptions}
                  value={template.language ?? "auto"}
                  onChange={(value) =>
                    autosave.patch({ language: value as WidgetTemplate["language"] })
                  }
                  width="100%"
                />
                <div className="sm:col-span-2">
                  <DraftWrapper onFocus={description.onFocus} onBlur={description.onBlur}>
                    <TextArea
                      label={t("description")}
                      description={t("widget_admin_template_description_description")}
                      value={description.text}
                      maxLength={500}
                      rows={2}
                      width="100%"
                      onChange={(value) => {
                        description.setText(value);
                        autosave.patch({ description: value });
                      }}
                    />
                  </DraftWrapper>
                </div>
              </div>
              <Switch
                label={t("widget_admin_template_default")}
                description={t("widget_admin_template_default_description")}
                value={template.is_default}
                labelPosition="start"
                labelSpacing="spread"
                width="100%"
                onChange={(checked) => autosave.patch({ is_default: checked })}
              />
            </SettingsGroup>

            <SettingsGroup
              title={t("widget_admin_template_locks")}
              description={t("widget_admin_template_locks_description")}
            >
              {LOCK_GROUPS.map((group) => {
                const blocked = group === "legal_texts" && !hasSubtitle && !legalLocked;
                return (
                  <Switch
                    key={group}
                    label={lockLabels[group].label}
                    description={
                      blocked
                        ? `${lockLabels[group].description} ${t("widget_admin_template_lock_needs_subtitle")}`
                        : lockLabels[group].description
                    }
                    value={template.locked_groups.includes(group)}
                    isDisabled={blocked}
                    disabledMessage={
                      blocked ? t("widget_admin_template_lock_needs_subtitle") : undefined
                    }
                    labelPosition="start"
                    labelSpacing="spread"
                    width="100%"
                    onChange={(checked) => setLock(group, checked)}
                  />
                );
              })}
            </SettingsGroup>

            <TabList
              role="tablist"
              aria-label={t("widget_admin_template_details")}
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
            </TabList>

            {panel(
              "content",
              <>
                <SettingsGroup
                  title={t("widget_admin_texts")}
                  description={t("widget_admin_template_texts_description")}
                >
                  {state.refusals["texts"] && (
                    <p className="text-ax-red text-sm">{state.refusals["texts"]}</p>
                  )}
                  <WidgetTextsFields
                    texts={template.texts}
                    showSuggestions={false}
                    errors={textErrors}
                    subtitleRequired={
                      legalLocked ? t("widget_admin_blocker_legal_texts_lock_subtitle") : undefined
                    }
                    onChange={(change) =>
                      autosave.patch({ texts: { ...autosave.widget.texts, ...change } })
                    }
                  />
                </SettingsGroup>
                <SettingsGroup
                  title={t("widget_admin_persona")}
                  description={t("widget_admin_template_persona_description")}
                >
                  {state.refusals["persona"] && (
                    <p className="text-ax-red text-sm">{state.refusals["persona"]}</p>
                  )}
                  <WidgetPersonaFields
                    persona={template.persona ?? {}}
                    chatTitle={template.texts.title ?? ""}
                    errors={personaErrors}
                    onChange={(persona) => autosave.patch({ persona })}
                  />
                </SettingsGroup>
              </>
            )}
            {panel(
              "appearance",
              <SettingsGroup
                title={t("widget_admin_appearance")}
                description={t("widget_admin_appearance_description")}
              >
                {state.refusals["theme"] && (
                  <p className="text-ax-red text-sm">{state.refusals["theme"]}</p>
                )}
                <WidgetThemeFields
                  theme={template.theme}
                  onChange={(change) =>
                    autosave.patch({ theme: { ...autosave.widget.theme, ...change } })
                  }
                />
              </SettingsGroup>
            )}
          </div>

          <aside className="min-w-0 self-start xl:sticky xl:top-6">
            <WidgetMockPreview
              name={template.name}
              texts={template.texts}
              theme={template.theme}
              persona={template.persona}
            />
          </aside>
        </div>
      </div>

      <Dialog
        isOpen={confirmOpen}
        onOpenChange={(open) => {
          if (!publishing) setConfirmOpen(open);
        }}
        purpose="form"
        width={480}
      >
        <Layout
          height="auto"
          header={
            <DialogHeader
              title={
                template.linked_widgets === 1
                  ? t("widget_admin_template_publish_confirm_title_one")
                  : t("widget_admin_template_publish_confirm_title", {
                      count: String(template.linked_widgets)
                    })
              }
              onOpenChange={(open) => {
                if (!publishing) setConfirmOpen(open);
              }}
            />
          }
          content={
            <LayoutContent>
              <div className="flex flex-col gap-3">
                <p className="text-ax-text-secondary text-sm">
                  {t("widget_admin_template_publish_confirm_description")}
                </p>
                <ul
                  className="flex list-disc flex-col gap-1 pl-5 text-sm"
                  aria-label={t("widget_admin_template_publish_changes_label")}
                >
                  {summary.written.length > 0 && (
                    <li>
                      {t("widget_admin_template_publish_writes", {
                        parts: groupNames(summary.written)
                      })}
                    </li>
                  )}
                  {summary.newlyLocked.length > 0 && (
                    <li>
                      {t("widget_admin_template_publish_new_locks", {
                        parts: groupNames(summary.newlyLocked)
                      })}
                    </li>
                  )}
                  {summary.released.length > 0 && (
                    <li>
                      {t("widget_admin_template_publish_released_locks", {
                        parts: groupNames(summary.released)
                      })}
                    </li>
                  )}
                  {summary.changedUnlocked.length > 0 && (
                    <li>
                      {t("widget_admin_template_publish_unlocked_changes", {
                        parts: groupNames(summary.changedUnlocked)
                      })}
                    </li>
                  )}
                  {changesNothing && (
                    <li>{t("widget_admin_template_publish_no_widget_changes")}</li>
                  )}
                </ul>
              </div>
            </LayoutContent>
          }
          footer={
            <LayoutFooter>
              <div className="flex flex-wrap justify-end gap-2">
                <Button
                  label={t("cancel")}
                  isDisabled={publishing}
                  onClick={() => setConfirmOpen(false)}
                />
                <Button
                  variant="primary"
                  label={t("widget_admin_template_publish")}
                  isLoading={publishing}
                  isInterruptible
                  clickAction={publish}
                />
              </div>
            </LayoutFooter>
          }
        />
      </Dialog>
    </SaveStatusProvider>
  );
}
