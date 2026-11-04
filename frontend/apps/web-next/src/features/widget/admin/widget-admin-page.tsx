"use client";

import { Button } from "@astryxdesign/core/Button";
import { useQuery, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import { useId, useRef, useState } from "react";
import { TextInput } from "@/components/astryx/text-input";
import { PageFrame, PAGE_COLUMN } from "@/components/composites/page-frame";
import { PageHeader } from "@/components/composites/page-header";
import { SaveStatusIndicator, SaveStatusProvider } from "@/components/composites/save-status";
import { SettingsGroup } from "@/components/composites/settings-rows";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import { assistantQueryOptions } from "@/features/assistants/editor/use-assistant";
import { useSpaceDisplayName } from "@/features/spaces/space-display-name";
import { spaceLandingHref, spaceSections } from "@/features/spaces/frame/space-sections";
import { useSpace } from "@/features/spaces/use-space";
import {
  spaceWidgetsQueryOptions,
  widgetApi,
  widgetPolicyQueryOptions,
  widgetTemplatesQueryOptions,
  type Widget,
  type WidgetTemplate
} from "./queries";
import { WIDGET_OVERVIEW_KEY } from "./org/queries";
import type { LoaderRelease } from "@eneo/eneo-js/widgets/snippet";
import { TemplatePicker } from "./template-picker";
import { WidgetEditor } from "./widget-editor";

/**
 * The widget of one assistant: its editor, or the form that creates it. The
 * page owns its surface like the editors do: a sticky header with the
 * breadcrumb back to the assistant, the save state, then the editor.
 */
export function WidgetAdminPage({
  assistantId,
  release,
  appOrigin
}: {
  assistantId: string;
  /** The loader build this installation serves, for the snippet; null when it has none. */
  release: LoaderRelease | null;
  /** Public origin of this installation (APP_ORIGIN): what the snippet points other sites at. */
  appOrigin: string;
}) {
  const t = useTranslations();
  const { space, routeId, can: spaceCan } = useSpace();
  const { can } = useAppContext();
  const spaceName = useSpaceDisplayName();
  const queryClient = useQueryClient();
  const { data: assistant } = useSuspenseQuery(assistantQueryOptions(browserApi, assistantId));
  const { data: widgets } = useSuspenseQuery(spaceWidgetsQueryOptions(browserApi, space.id));
  const policy = useQuery(widgetPolicyQueryOptions(browserApi));
  const templatesQuery = useQuery(widgetTemplatesQueryOptions(browserApi));
  const isAdmin = can("admin");

  const widget =
    widgets.find(
      (candidate) => candidate.target_id === assistantId && candidate.status !== "archived"
    ) ?? null;

  // The archive dialog's trigger goes with the editor, so the focus it would
  // return there moves to the note saying what happened.
  const [reloadCount, setReloadCount] = useState(0);
  const [archived, setArchived] = useState(false);
  const archivedNote = useRef<HTMLParagraphElement>(null);

  function replaceInList(updated: Widget | null, previousId?: string) {
    const key = spaceWidgetsQueryOptions(browserApi, space.id).queryKey;
    const before = (queryClient.getQueryData<Widget[]>(key) ?? []).find(
      (item) => item.id === (updated?.id ?? previousId)
    );
    queryClient.setQueryData(key, (current: Widget[] | undefined) => {
      const rest = (current ?? []).filter(
        (item) => item.id !== previousId && item.id !== updated?.id
      );
      return updated ? [...rest, updated] : rest;
    });
    // A template's follower count lives in its own cache; a widget that
    // starts or stops following one changes it.
    if ((before?.template?.id ?? null) !== (updated?.template?.id ?? null)) {
      void queryClient.invalidateQueries({ queryKey: ["widget-templates"] });
    }
    // The organisation's overview folds each widget's blockers in.
    void queryClient.invalidateQueries({ queryKey: WIDGET_OVERVIEW_KEY });
  }

  const sections = spaceSections(space, spaceCan, routeId);
  const header = (
    <PageHeader
      title={t("widget_admin_title")}
      breadcrumbs={[
        { label: spaceName, href: spaceLandingHref(sections, routeId) },
        { label: t("assistants"), href: `/spaces/${routeId}/assistants` },
        { label: assistant.name, href: `/spaces/${routeId}/assistants/${assistantId}/edit` },
        { label: t("widget_admin_title"), current: true }
      ]}
      actions={<SaveStatusIndicator />}
      className="py-3"
    />
  );

  return (
    <SaveStatusProvider>
      <div data-space-full-bleed className="flex shrink-0 flex-col">
        <header className="bg-ax-surface border-ax-border sticky top-0 z-30 border-b">
          <div className="wide:px-6 px-4">
            <div className={`${PAGE_COLUMN} flex flex-col gap-1`}>{header}</div>
          </div>
        </header>
        <PageFrame className="gap-6">
          {widget ? (
            <WidgetEditor
              key={`${widget.id}-${reloadCount}`}
              widget={widget}
              assistant={assistant}
              isAdmin={isAdmin}
              policy={policy.data ?? null}
              release={release}
              appOrigin={appOrigin}
              templates={templatesQuery.data ?? []}
              onReloaded={(saved) => {
                replaceInList(saved);
                setReloadCount((count) => count + 1);
              }}
              onSaved={(updated) => replaceInList(updated)}
              onArchived={() => {
                replaceInList(null, widget.id);
                setArchived(true);
                requestAnimationFrame(() => archivedNote.current?.focus());
              }}
            />
          ) : (
            <>
              {archived && (
                <p
                  ref={archivedNote}
                  tabIndex={-1}
                  className="bg-ax-muted w-full max-w-3xl rounded-lg px-4 py-3 text-sm"
                >
                  {t("widget_admin_archived_note")}
                </p>
              )}
              <CreateWidgetForm
                assistantName={assistant.name}
                assistantId={assistantId}
                spaceId={space.id}
                templates={(templatesQuery.data ?? []).filter((item) => item.published_at != null)}
                unsupportedSpace={
                  space.organization
                    ? t("widget_admin_blocker_organization_space_unsupported")
                    : space.personal
                      ? t("widget_admin_blocker_personal_space_unsupported")
                      : null
                }
                onCreated={(created) => {
                  replaceInList(created);
                  setArchived(false);
                }}
              />
            </>
          )}
        </PageFrame>
      </div>
    </SaveStatusProvider>
  );
}

function CreateWidgetForm({
  assistantName,
  assistantId,
  spaceId,
  templates,
  unsupportedSpace,
  onCreated
}: {
  assistantName: string;
  assistantId: string;
  spaceId: string;
  templates: WidgetTemplate[];
  /** Why no widget can be created in this space, or null. */
  unsupportedSpace: string | null;
  onCreated: (widget: Widget) => void;
}) {
  const t = useTranslations();
  const formId = useId();
  const [name, setName] = useState(assistantName);
  const [templateId, setTemplateId] = useState(
    () => templates.find((template) => template.is_default)?.id ?? ""
  );
  const [creating, setCreating] = useState(false);

  async function create() {
    if (creating) return;
    setCreating(true);
    try {
      onCreated(
        await widgetApi.create(spaceId, {
          target_id: assistantId,
          name: name.trim() || assistantName,
          language: "auto",
          template_id: templateId || null
        })
      );
    } catch (error) {
      toastApiError(error, t);
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="w-full max-w-3xl">
      <SettingsGroup
        title={unsupportedSpace ? t("widget_admin_title") : t("widget_admin_create_title")}
        description={unsupportedSpace ?? t("widget_admin_create_description")}
      >
        {!unsupportedSpace && (
          <form
            id={formId}
            className="flex flex-col gap-6"
            onSubmit={(event) => {
              event.preventDefault();
              void create();
            }}
          >
            <TextInput
              label={t("name")}
              description={t("widget_admin_name_description")}
              value={name}
              onChange={(value) => setName(value.slice(0, 100))}
              isRequired
              width="100%"
            />
            {templates.length > 0 && (
              <div className="flex flex-col gap-2">
                <p className="text-sm font-medium">{t("widget_admin_template")}</p>
                <p className="text-ax-text-secondary text-sm">
                  {t("widget_admin_template_create_help")}
                </p>
                <TemplatePicker
                  templates={templates}
                  value={templateId}
                  onChange={setTemplateId}
                  includeNone
                  legend={t("widget_admin_template")}
                />
              </div>
            )}
            <div>
              <Button
                type="submit"
                variant="primary"
                label={t("widget_admin_create")}
                isLoading={creating}
                isInterruptible
              />
            </div>
          </form>
        )}
      </SettingsGroup>
    </div>
  );
}
