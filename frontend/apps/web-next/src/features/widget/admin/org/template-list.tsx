"use client";

import { AlertDialog } from "@astryxdesign/core/AlertDialog";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Star, StarOff, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";
import { SettingsGroup } from "@/components/composites/settings-rows";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import { DEFAULT_PRIMARY_COLOR, isHexColor } from "../../contrast";
import type { WidgetTemplate } from "../autosave";
import { toastWidgetError } from "../errors";
import { widgetTemplatesQueryOptions } from "../queries";
import { widgetTemplateApi } from "./queries";

export const templateHref = (id: string) => `/admin/widgets/templates/${id}`;

/**
 * The organisation's widget templates: the house styles editors start from.
 * Creating one opens its editor; the default is what new widgets get
 * preselected; deleting asks first and is refused while widgets follow it.
 */
export function TemplateList({ templates }: { templates: WidgetTemplate[] }) {
  const t = useTranslations();
  const locale = useLocale();
  const router = useRouter();
  const queryClient = useQueryClient();
  const number = new Intl.NumberFormat(locale === "sv" ? "sv-SE" : "en-US");
  const [creating, setCreating] = useState(false);
  const [toDelete, setToDelete] = useState<WidgetTemplate | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const key = widgetTemplatesQueryOptions(browserApi).queryKey;
  const replace = (next: (current: WidgetTemplate[]) => WidgetTemplate[]) =>
    queryClient.setQueryData(key, (current: WidgetTemplate[] | undefined) => next(current ?? []));

  async function create() {
    if (creating) return;
    setCreating(true);
    try {
      const created = await widgetTemplateApi.create({ name: t("widget_admin_template_new_name") });
      replace((current) => [...current, created]);
      router.push(templateHref(created.id));
    } catch (error) {
      toastApiError(error, t);
      setCreating(false);
    }
  }

  async function setDefault(template: WidgetTemplate, isDefault: boolean) {
    if (busyId) return;
    setBusyId(template.id);
    try {
      const updated = await widgetTemplateApi.update(template.id, { is_default: isDefault });
      replace((current) =>
        current.map((item) =>
          item.id === updated.id ? updated : isDefault ? { ...item, is_default: false } : item
        )
      );
    } catch (error) {
      toastApiError(error, t);
    } finally {
      setBusyId(null);
    }
  }

  async function remove() {
    const target = toDelete;
    if (!target || deleting) return;
    setDeleting(true);
    try {
      await widgetTemplateApi.delete(target.id);
      replace((current) => current.filter((item) => item.id !== target.id));
      setToDelete(null);
    } catch (error) {
      toastWidgetError(error, t);
    } finally {
      setDeleting(false);
    }
  }

  const languageLabel = (language: WidgetTemplate["language"]) =>
    language === "sv"
      ? t("widget_admin_language_sv")
      : language === "en"
        ? t("widget_admin_language_en")
        : t("widget_admin_language_auto");
  const accent = (template: WidgetTemplate) => {
    const colour = template.theme.primary_color ?? "";
    return isHexColor(colour) ? colour : DEFAULT_PRIMARY_COLOR;
  };
  const header = (template: WidgetTemplate) => {
    const colour = template.theme.header_color ?? "";
    return isHexColor(colour) ? colour : null;
  };

  return (
    <SettingsGroup
      title={t("widget_admin_templates")}
      description={t("widget_admin_templates_description")}
      headerEnd={
        <Button
          variant="primary"
          label={t("widget_admin_template_new")}
          icon={<Plus aria-hidden="true" className="size-4" />}
          isLoading={creating}
          isInterruptible
          clickAction={create}
        />
      }
    >
      {templates.length === 0 ? (
        <p className="text-ax-text-secondary text-sm">{t("widget_admin_templates_empty")}</p>
      ) : (
        <ul className="divide-ax-border -my-2 divide-y" aria-label={t("widget_admin_templates")}>
          {templates.map((template) => (
            <li key={template.id} className="flex flex-wrap items-center gap-4 py-4">
              <span className="flex shrink-0 items-center gap-1" aria-hidden="true">
                <span
                  className="border-ax-border inline-block size-8 rounded-full border"
                  style={{ background: accent(template) }}
                />
                <span
                  className="border-ax-border inline-block h-8 w-5 rounded-md border"
                  style={{ background: header(template) ?? "transparent" }}
                />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Link
                    className="font-medium underline-offset-2 hover:underline"
                    href={templateHref(template.id)}
                  >
                    {template.name}
                  </Link>
                  {template.is_default && (
                    <Badge variant="info" label={t("widget_admin_template_default")} />
                  )}
                  {template.published_at == null ? (
                    <Badge variant="neutral" label={t("widget_admin_template_unpublished")} />
                  ) : (
                    template.has_unpublished_changes && (
                      <Badge
                        variant="warning"
                        label={t("widget_admin_template_unpublished_changes")}
                      />
                    )
                  )}
                  {template.linked_widgets > 0 && (
                    <Badge
                      variant="neutral"
                      label={
                        template.linked_widgets === 1
                          ? t("widget_admin_template_linked_count_one")
                          : t("widget_admin_template_linked_count", {
                              count: number.format(template.linked_widgets)
                            })
                      }
                    />
                  )}
                  <span className="text-ax-text-secondary text-xs">
                    {languageLabel(template.language)}
                  </span>
                </div>
                {template.description && (
                  <p className="text-ax-text-secondary text-sm">{template.description}</p>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  label={t("edit")}
                  icon={<Pencil aria-hidden="true" className="size-4" />}
                  href={templateHref(template.id)}
                  as={Link}
                />
                <Button
                  size="sm"
                  label={
                    template.is_default
                      ? t("widget_admin_template_unset_default")
                      : t("widget_admin_template_set_default")
                  }
                  icon={
                    template.is_default ? (
                      <StarOff aria-hidden="true" className="size-4" />
                    ) : (
                      <Star aria-hidden="true" className="size-4" />
                    )
                  }
                  isLoading={busyId === template.id}
                  isInterruptible
                  clickAction={() => setDefault(template, !template.is_default)}
                />
                <Button
                  size="sm"
                  variant="destructive"
                  label={t("delete")}
                  icon={<Trash2 aria-hidden="true" className="size-4" />}
                  tooltip={t("widget_admin_template_delete_named", { name: template.name })}
                  onClick={() => setToDelete(template)}
                />
              </div>
            </li>
          ))}
        </ul>
      )}

      <AlertDialog
        isOpen={toDelete !== null}
        onOpenChange={(open) => {
          if (!open && !deleting) setToDelete(null);
        }}
        title={t("widget_admin_template_delete_title")}
        description={t("widget_admin_template_delete_description")}
        actionLabel={t("delete")}
        cancelLabel={t("cancel")}
        actionVariant="destructive"
        isActionLoading={deleting}
        onAction={() => void remove()}
      />
    </SettingsGroup>
  );
}
