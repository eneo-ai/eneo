import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Collapsible } from "@astryxdesign/core/Collapsible";
import { DropdownMenu } from "@astryxdesign/core/DropdownMenu";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, MoreHorizontal, TriangleAlert } from "lucide-react";
import { useId, useRef, useState } from "react";
import { useLocale, useTranslations } from "use-intl";
import { ListError, QueryStateBoundary } from "@/components/composites/query-state";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import {
  documentTemplatesQueryOptions,
  DOCUMENT_TEMPLATES_KEY,
  deleteDocumentTemplate,
  downloadDocumentTemplate,
  downloadBuiltinDocumentTemplate,
  updateDocumentTemplate,
  type DocumentTemplate
} from "@/features/document-templates/document-templates";
import { browserApi } from "@/lib/api/browser";
import { formatBytes } from "@/lib/format";
import { saveBlob } from "@/features/files/signed-file-url";
import { useRemovalMutation } from "@/features/spaces/removal";
import { useFocusRescue } from "@/lib/focus-rescue";
import { OUTLINE_BUTTON_CLASS } from "./bundled";
import { DocumentTemplateDialog, type DocumentTemplateAction } from "./document-template-dialog";

const STATUS_LABELS = {
  ready: "document_template_status_ready",
  invalid: "document_template_status_invalid",
  unchecked: "document_template_status_unchecked"
} as const satisfies Record<DocumentTemplate["status"], string>;
const CHECK_LABELS: Record<string, string> = {
  content_placeholder: "document_template_check_content_placeholder",
  heading_styles: "document_template_check_heading_styles",
  title_style: "document_template_check_title_style",
  list_styles: "document_template_check_list_styles",
  table_style: "document_template_check_table_style",
  language: "document_template_check_language"
};
const AUTO_FIELDS = new Set([
  "title",
  "titel",
  "rubrik",
  "date",
  "datum",
  "year",
  "år",
  "organisation",
  "organization",
  "organisationen",
  "author",
  "författare",
  "forfattare"
]);
const CONTENT_FIELDS = new Set(["content", "dokument", "innehåll", "innehall", "body"]);

type ImmediateAction =
  | { kind: "default"; template: DocumentTemplate }
  | { kind: "download"; template: DocumentTemplate }
  | { kind: "builtin"; language: "sv" | "en" };

function TemplateChecks({ template }: { template: DocumentTemplate }) {
  const t = useTranslations();
  const [expanded, setExpanded] = useState(false);
  const seen = new Set<string>();
  const fields = template.placeholders.filter((field) => {
    if (seen.has(field.name)) return false;
    seen.add(field.name);
    return true;
  });
  return (
    <Collapsible
      trigger={t(expanded ? "document_template_hide_checks" : "document_template_show_checks")}
      isOpen={expanded}
      onOpenChange={setExpanded}
    >
      <div className="bg-ax-muted rounded-ax-element space-y-3 p-3 text-sm">
        {template.status === "unchecked" ? (
          <p>{t("document_template_unchecked")}</p>
        ) : (
          <>
            {template.status === "invalid" && <p>{t("document_template_invalid")}</p>}
            <h4 className="font-medium">{t("document_template_checks")}</h4>
            <ul className="space-y-2">
              {Object.entries(template.checks).map(([name, check]) => {
                const labelKey = Object.hasOwn(CHECK_LABELS, name) ? CHECK_LABELS[name] : undefined;
                return (
                  <li key={name} className="flex items-start gap-2">
                    {check.ok ? (
                      <Check aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                    ) : (
                      <TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                    )}
                    <span>
                      <span className="sr-only">
                        {t(
                          check.ok
                            ? "document_template_check_passed"
                            : "document_template_check_failed"
                        )}
                        :{" "}
                      </span>
                      {labelKey ? t(labelKey) : name} ·{" "}
                      <span className="text-ax-text-secondary">{check.detail}</span>
                    </span>
                  </li>
                );
              })}
            </ul>
            <h4 className="font-medium">{t("document_template_fields")}</h4>
            {fields.length === 0 ? (
              <p className="text-ax-text-secondary">{t("document_template_no_fields")}</p>
            ) : (
              <ul className="space-y-2">
                {fields.map((field) => (
                  <li key={field.name}>
                    <code>{field.name}</code>
                    {field.label && field.label !== field.name && <span> ({field.label})</span>}
                    {!field.supported ? (
                      <span> · {t("document_template_field_unsupported")}</span>
                    ) : (
                      !CONTENT_FIELDS.has(field.name.toLowerCase()) && (
                        <span>
                          {" "}
                          ·{" "}
                          {t(
                            AUTO_FIELDS.has(field.name.toLowerCase())
                              ? "document_template_field_auto"
                              : "document_template_field_assistant"
                          )}
                        </span>
                      )
                    )}
                    {field.hint && (
                      <p className="text-ax-text-secondary mt-1 text-xs">{field.hint}</p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </Collapsible>
  );
}

export function DocumentTemplatesSection() {
  const t = useTranslations();
  const locale = useLocale();
  const announce = useAnnounce();
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const rescueFocus = useFocusRescue();
  const queryClient = useQueryClient();
  const [action, setAction] = useState<DocumentTemplateAction | null>(null);
  const [deleting, setDeleting] = useState<DocumentTemplate | null>(null);
  const [failed, setFailed] = useState<ImmediateAction | null>(null);
  const templates = useQuery(documentTemplatesQueryOptions(browserApi));
  const refresh = () => queryClient.invalidateQueries({ queryKey: DOCUMENT_TEMPLATES_KEY });
  const remove = useRemovalMutation({
    mutationFn: (template: DocumentTemplate) => deleteDocumentTemplate(browserApi, template.id),
    refresh: () =>
      Promise.all([
        refresh(),
        // Deletion also removes assistant bindings; their next read must see default mode.
        queryClient.invalidateQueries({ queryKey: ["assistants"] })
      ]),
    onRemoved: () => {
      setDeleting(null);
      announce(t("document_template_removed"));
    },
    onError: () => {},
    focusTarget: headingRef
  });
  const immediate = useMutation({
    mutationFn: async (operation: ImmediateAction) => {
      if (operation.kind === "default") {
        await updateDocumentTemplate(browserApi, operation.template.id, { is_default: true });
        await refresh();
      } else if (operation.kind === "download") {
        saveBlob(
          await downloadDocumentTemplate(browserApi, operation.template.id),
          operation.template.filename
        );
      } else {
        saveBlob(
          await downloadBuiltinDocumentTemplate(browserApi, operation.language),
          `eneo-template-${operation.language}.docx`
        );
      }
    },
    onError: (_error, operation) => setFailed(operation),
    onSuccess: (_data, operation) => {
      setFailed(null);
      rescueFocus(() => headingRef.current);
      announce(
        t(
          operation.kind === "default"
            ? "document_template_saved"
            : "document_template_download_started"
        )
      );
    }
  });
  function run(operation: ImmediateAction) {
    if (immediate.isPending) return;
    if (failed !== operation) setFailed(null);
    immediate.mutate(operation);
  }
  return (
    <section className="space-y-3 border-t p-5" aria-labelledby={headingId}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id={headingId} ref={headingRef} tabIndex={-1} className="font-medium">
            {t("document_templates")}
          </h3>
          <p className="text-ax-text-secondary mt-1 max-w-prose text-sm">
            {t("document_templates_description")}
          </p>
        </div>
        {templates.data && (
          // Outlines, like every button on the Verktyg page.
          <Button
            label={t("document_template_upload")}
            variant="ghost"
            className={OUTLINE_BUTTON_CLASS}
            size="sm"
            onClick={() => {
              const data = templates.data;
              if (data)
                setAction({
                  kind: "upload",
                  isDefault: !data.items.some((template) => template.is_default)
                });
            }}
          />
        )}
      </div>
      {failed && (
        <div className="space-y-2">
          <p className="text-sm font-medium">
            {failed.kind === "builtin" ? t("document_template_builtin_name") : failed.template.name}
          </p>
          {immediate.error && (
            <ListError
              error={immediate.error}
              title={t(
                failed.kind === "default"
                  ? "document_template_could_not_save"
                  : "document_template_could_not_download"
              )}
            />
          )}
          <Button
            label={t("retry")}
            variant="ghost"
            className={OUTLINE_BUTTON_CLASS}
            size="sm"
            isLoading={immediate.isPending}
            isInterruptible
            onClick={() => run(failed)}
          />
        </div>
      )}
      <QueryStateBoundary query={templates} rows={2} errorTitle={t("document_templates")}>
        {(data) =>
          data === null ? (
            <p className="text-ax-text-secondary text-sm">{t("document_template_not_supported")}</p>
          ) : (
            <>
              {data.items.length === 0 && (
                <p className="text-ax-text-secondary text-sm">{t("document_template_empty")}</p>
              )}
              <ul aria-labelledby={headingId} className="rounded-ax-element divide-y border">
                {data.items.map((template) => {
                  const warnings = Object.values(template.checks).filter(
                    (check) => !check.ok
                  ).length;
                  return (
                    <li key={template.id} className="space-y-3 p-4">
                      <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <span className="font-medium break-words">{template.name}</span>
                        {template.is_default && <Badge label={t("document_template_default")} />}
                        {template.status === "ready" ? (
                          <span className="text-ax-text-secondary text-sm">
                            {t(STATUS_LABELS.ready)}
                          </span>
                        ) : (
                          <Badge
                            variant={template.status === "invalid" ? "warning" : "neutral"}
                            label={t(STATUS_LABELS[template.status])}
                          />
                        )}
                        {template.status === "ready" && warnings > 0 && (
                          <Badge
                            variant="warning"
                            label={t("document_template_warnings", { count: warnings })}
                          />
                        )}
                        <div className="ms-auto shrink-0">
                          <DropdownMenu
                            button={{
                              label: `${t("actions")}: ${template.name}`,
                              icon: <MoreHorizontal className="size-4" />,
                              isIconOnly: true,
                              variant: "ghost",
                              size: "sm",
                              isLoading:
                                immediate.isPending &&
                                immediate.variables.kind !== "builtin" &&
                                immediate.variables.template.id === template.id,
                              isInterruptible: true
                            }}
                            hasChevron={false}
                            presentation="adaptive"
                            alignment="end"
                            items={[
                              {
                                id: "rename",
                                label: t("document_template_rename"),
                                isDisabled: immediate.isPending,
                                onClick: () => setAction({ kind: "rename", template })
                              },
                              {
                                id: "replace",
                                label: t("document_template_replace_file"),
                                isDisabled: immediate.isPending,
                                onClick: () => setAction({ kind: "replace", template })
                              },
                              {
                                id: "default",
                                label: t("document_template_make_default"),
                                isDisabled: template.is_default || immediate.isPending,
                                onClick: () => run({ kind: "default", template })
                              },
                              {
                                id: "download",
                                label: t("document_template_download"),
                                isDisabled: immediate.isPending,
                                onClick: () => run({ kind: "download", template })
                              },
                              { type: "divider" },
                              {
                                id: "delete",
                                label: t("document_template_delete"),
                                isDisabled: immediate.isPending,
                                variant: "destructive",
                                onClick: () => {
                                  remove.reset();
                                  setDeleting(template);
                                }
                              }
                            ]}
                          />
                        </div>
                      </div>
                      <p className="text-ax-text-secondary text-sm break-words">
                        {template.filename} · {formatBytes(template.size_bytes, locale)}
                        {template.selected_by > 0 && (
                          <>
                            {" "}
                            · {t("document_template_selected_by", { count: template.selected_by })}
                          </>
                        )}
                      </p>
                      <TemplateChecks template={template} />
                    </li>
                  );
                })}
                <li className="space-y-1 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{t("document_template_builtin_name")}</span>
                    {!data.items.some((template) => template.is_default) && (
                      <Badge label={t("document_template_default")} />
                    )}
                  </div>
                  <p className="text-ax-text-secondary text-sm">
                    {t("document_template_builtin_description")}
                  </p>
                  {!data.runtime_configured && (
                    <p className="text-ax-text-secondary text-sm">
                      {t("document_template_builtin_unavailable")}
                    </p>
                  )}
                  <Button
                    label={t("document_template_download_builtin")}
                    variant="ghost"
                    className={OUTLINE_BUTTON_CLASS}
                    size="sm"
                    isDisabled={!data.runtime_configured}
                    isLoading={immediate.isPending && immediate.variables.kind === "builtin"}
                    isInterruptible
                    onClick={() =>
                      run({ kind: "builtin", language: locale === "sv" ? "sv" : "en" })
                    }
                  />
                </li>
              </ul>
            </>
          )
        }
      </QueryStateBoundary>
      <ConfirmDialogControlled
        open={deleting !== null}
        onOpenChange={(open) => {
          if (!open) setDeleting(null);
        }}
        title={t("document_template_delete")}
        description={t("document_template_delete_confirmation")}
        confirmLabel={t("document_template_delete")}
        pending={remove.isPending}
        onConfirm={() => {
          if (deleting && !remove.isPending) remove.mutate(deleting);
        }}
      >
        <p className="font-medium break-words">{deleting?.name}</p>
        {remove.error && (
          <ListError error={remove.error} title={t("document_template_could_not_delete")} />
        )}
      </ConfirmDialogControlled>
      {action && (
        <DocumentTemplateDialog
          key={action.kind === "upload" ? "upload" : `${action.kind}:${action.template.id}`}
          action={action}
          onClose={() => setAction(null)}
          onSaved={async () => {
            await refresh();
            setAction(null);
            announce(t("document_template_saved"));
          }}
        />
      )}
    </section>
  );
}
