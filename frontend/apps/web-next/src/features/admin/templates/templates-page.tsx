"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { Button as AstryxButton } from "@astryxdesign/core/Button";
import {
  DropdownMenu,
  DropdownMenuDivider,
  DropdownMenuItem
} from "@astryxdesign/core/DropdownMenu";
import { useCollator } from "@astryxdesign/core/i18n";
import {
  pixel,
  proportional,
  type TableColumn,
  type TableSortComparator,
  useTableSortable,
  useTableSortableState
} from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { Tooltip } from "@astryxdesign/core/Tooltip";
import { VisuallyHidden } from "@astryxdesign/core/VisuallyHidden";
import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { MoreHorizontal, Pencil, Plus, RotateCcw, Star, Trash2 } from "lucide-react";
import { useTranslations } from "use-intl";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { Table } from "@/components/astryx/table";
import { ClientTime } from "@/components/composites/client-time";
import { ConfirmDialog, ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { EmptyState } from "@/components/composites/empty-state";
import { PageHeader } from "@/components/composites/page-header";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { useAppContext } from "@/components/providers/app-context";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { useRouter } from "@/lib/navigation";
import { matchesSearch } from "@/lib/search";
import { INPUT_TYPE_META, isInputFieldType } from "@/features/apps/editor/input-type-select";
import { RemovalFocusScope, useRemovalMutation } from "@/features/spaces/removal";
import { ResourceFilterInput } from "@/features/spaces/resource-filter-input";
import { TemplateIcon } from "@/features/templates/template-icon";
import {
  APP_KEY,
  ASSISTANT_KEY,
  DELETED_APP_KEY,
  DELETED_ASSISTANT_KEY,
  type AppTemplate,
  type AssistantTemplate,
  type TemplateKind,
  appTemplatesQueryOptions,
  assistantTemplatesQueryOptions,
  deletedAppTemplatesQueryOptions,
  deletedAssistantTemplatesQueryOptions,
  rollbackAppTemplate,
  rollbackAssistantTemplate,
  templateCategoryInfo
} from "@/features/admin/templates/templates";
import { TemplateEditorDialog } from "./template-editor-dialog";

type TemplateData = AssistantTemplate | AppTemplate;
type Translate = ReturnType<typeof useTranslations>;

function deleteTemplate(kind: TemplateKind, templateId: string) {
  const params = { path: { template_id: templateId } };
  return kind === "assistants"
    ? unwrap(browserApi.DELETE("/api/v1/admin/templates/assistants/{template_id}", { params }))
    : unwrap(browserApi.DELETE("/api/v1/admin/templates/apps/{template_id}", { params }));
}

function toggleDefault(kind: TemplateKind, templateId: string, isDefault: boolean) {
  const params = { path: { template_id: templateId } };
  const body = { is_default: isDefault };
  return kind === "assistants"
    ? unwrap(
        browserApi.PATCH("/api/v1/admin/templates/assistants/{template_id}/default", {
          params,
          body
        })
      )
    : unwrap(
        browserApi.PATCH("/api/v1/admin/templates/apps/{template_id}/default", { params, body })
      );
}

function restoreTemplate(kind: TemplateKind, templateId: string) {
  const params = { path: { template_id: templateId } };
  return kind === "assistants"
    ? unwrap(
        browserApi.POST("/api/v1/admin/templates/assistants/{template_id}/restore", { params })
      )
    : unwrap(browserApi.POST("/api/v1/admin/templates/apps/{template_id}/restore", { params }));
}

function rollbackTemplate(kind: TemplateKind, templateId: string) {
  return kind === "assistants"
    ? rollbackAssistantTemplate(browserApi, templateId)
    : rollbackAppTemplate(browserApi, templateId);
}

function permanentDelete(kind: TemplateKind, templateId: string) {
  const params = { path: { template_id: templateId } };
  return kind === "assistants"
    ? unwrap(
        browserApi.DELETE("/api/v1/admin/templates/assistants/{template_id}/permanent", { params })
      )
    : unwrap(browserApi.DELETE("/api/v1/admin/templates/apps/{template_id}/permanent", { params }));
}

const activeKey = (kind: TemplateKind) => (kind === "assistants" ? ASSISTANT_KEY : APP_KEY);
const deletedKey = (kind: TemplateKind) =>
  kind === "assistants" ? DELETED_ASSISTANT_KEY : DELETED_APP_KEY;

/** A template as a table row, with the texts the row shows, sorts and filters by. */
type TemplateRow = {
  /** Unique in its table: the deleted table holds both kinds. */
  id: string;
  kind: TemplateKind;
  template: TemplateData;
  category: { title: string; description: string | null };
  /** App templates: the stored input type and its name (the stored value when unknown). */
  inputType: string;
  inputTypeLabel: string;
  typeLabel: string;
  search: string[];
};

function toRow(kind: TemplateKind, template: TemplateData, t: Translate, id = template.id) {
  const category = templateCategoryInfo(kind, template.category, t);
  const inputType = "input_type" in template ? template.input_type : "";
  const inputTypeLabel = isInputFieldType(inputType)
    ? t(INPUT_TYPE_META[inputType].labelKey)
    : inputType;
  const typeLabel = kind === "assistants" ? t("assistant") : t("app");
  return {
    id,
    kind,
    template,
    category,
    inputType,
    inputTypeLabel,
    typeLabel,
    // What the Svelte tables filter on (name, category, input type, type), as stored and as shown.
    search: [template.name, template.category, category.title, inputType, inputTypeLabel, typeLabel]
  } satisfies TemplateRow;
}

type SortKey = "name" | "category" | "input_type" | "type" | "usage" | "created" | "deleted";

function time(value: string | null | undefined): number {
  const parsed = value ? Date.parse(value) : Number.NaN;
  return Number.isNaN(parsed) ? 0 : parsed;
}

/** Values, never labels, except where the label is what the column shows. */
function comparators(
  compare: (a: string, b: string) => number
): Record<SortKey, TableSortComparator<TemplateRow>> {
  return {
    name: (a, b) => compare(a.template.name, b.template.name),
    category: (a, b) => compare(a.category.title, b.category.title),
    input_type: (a, b) => compare(a.inputTypeLabel, b.inputTypeLabel),
    type: (a, b) => compare(a.typeLabel, b.typeLabel),
    usage: (a, b) => (a.template.usage_count ?? 0) - (b.template.usage_count ?? 0),
    created: (a, b) => time(a.template.created_at) - time(b.template.created_at),
    deleted: (a, b) => time(a.template.deleted_at) - time(b.template.deleted_at)
  };
}

/** Name with the template's icon, the featured mark and the description on one line. */
function TemplateNameCell({
  template,
  showDefault
}: {
  template: TemplateData;
  showDefault: boolean;
}) {
  const t = useTranslations();
  return (
    <div className="flex min-w-0 flex-col gap-0.5 py-1">
      <span className="flex min-w-0 items-center gap-2">
        {template.icon_name && (
          <span className="border-ax-border bg-ax-muted rounded-ax-inner flex size-6 shrink-0 items-center justify-center border">
            <TemplateIcon name={template.icon_name} className="size-4" />
          </span>
        )}
        <span className="truncate font-medium">{template.name}</span>
        {showDefault && template.is_default && (
          <Badge
            variant="neutral"
            icon={<Star aria-hidden="true" className="size-3 fill-current" />}
            label={t("featured")}
          />
        )}
      </span>
      {template.description && (
        // One line; the whole text shows on hover when it is cut.
        <Text type="supporting" maxLines={1}>
          {template.description}
        </Text>
      )}
    </div>
  );
}

function CategoryBadge({ category }: { category: TemplateRow["category"] }) {
  const badge = <Badge variant="blue" label={category.title} />;
  return category.description ? <Tooltip content={category.description}>{badge}</Tooltip> : badge;
}

function InputTypeCell({ row }: { row: TemplateRow }) {
  if (!isInputFieldType(row.inputType)) {
    return <span className="text-ax-text-secondary">{row.inputType || "—"}</span>;
  }
  const Icon = INPUT_TYPE_META[row.inputType].icon;
  return (
    <span className="flex items-center gap-2">
      <Icon aria-hidden="true" className="size-4 shrink-0" />
      {row.inputTypeLabel}
    </span>
  );
}

function UsageCell({ count }: { count: number }) {
  const t = useTranslations();
  return (
    <span className="text-ax-text-secondary tabular-nums">
      {count} {count === 1 ? t("instance") : t("instances")}
    </span>
  );
}

function DateCell({ value }: { value: string | null | undefined }) {
  return (
    <span className="text-ax-text-secondary whitespace-nowrap">
      {value ? <ClientTime value={value} format="auto" /> : "—"}
    </span>
  );
}

/** The row menu of an active template: edit, featured, rollback, delete. */
function TemplateActions({
  row,
  onEdit
}: {
  row: TemplateRow;
  onEdit: (row: TemplateRow) => void;
}) {
  const { template, kind } = row;
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [confirm, setConfirm] = useState<"delete" | "rollback" | null>(null);

  const refresh = () => queryClient.invalidateQueries({ queryKey: activeKey(kind) });

  const remove = useRemovalMutation({
    mutationFn: () => deleteTemplate(kind, template.id),
    refresh: () =>
      Promise.all([refresh(), queryClient.invalidateQueries({ queryKey: deletedKey(kind) })]),
    onRemoved: () => setConfirm(null)
  });
  const setDefault = useMutation({
    mutationFn: (isDefault: boolean) => toggleDefault(kind, template.id, isDefault),
    onSuccess: refresh,
    onError: (error) => toastApiError(error, t)
  });
  const rollback = useMutation({
    mutationFn: () => rollbackTemplate(kind, template.id),
    onSuccess: () => {
      void refresh();
      setConfirm(null);
    },
    onError: (error) => toastApiError(error, t)
  });

  const menuName = t("ui_more_actions_for", { name: template.name });
  return (
    <>
      <DropdownMenu
        button={{
          label: menuName,
          tooltip: menuName,
          icon: <MoreHorizontal className="size-4" aria-hidden="true" />,
          isIconOnly: true,
          variant: "ghost",
          size: "sm"
        }}
        hasChevron={false}
        alignment="end"
      >
        <DropdownMenuItem icon={Pencil} label={t("edit")} onClick={() => onEdit(row)} />
        <DropdownMenuItem
          icon={Star}
          label={template.is_default ? t("remove_default") : t("set_as_default")}
          isDisabled={setDefault.isPending}
          onClick={() => setDefault.mutate(!template.is_default)}
        />
        {template.original_snapshot ? (
          <DropdownMenuItem
            icon={RotateCcw}
            label={t("rollback")}
            onClick={() => setConfirm("rollback")}
          />
        ) : null}
        <DropdownMenuDivider />
        <DropdownMenuItem
          icon={Trash2}
          label={t("delete")}
          variant="destructive"
          onClick={() => setConfirm("delete")}
        />
      </DropdownMenu>
      <ConfirmDialogControlled
        open={confirm === "delete"}
        onOpenChange={(open) => setConfirm(open ? "delete" : null)}
        title={t("delete")}
        description={t("template_delete_confirm", { name: template.name })}
        confirmLabel={remove.isPending ? t("deleting") : t("delete")}
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
      <ConfirmDialogControlled
        open={confirm === "rollback"}
        onOpenChange={(open) => setConfirm(open ? "rollback" : null)}
        title={t("rollback_template")}
        description={`${t("rollback_template_confirmation")} ${t("rollback_template_description")}`}
        confirmLabel={rollback.isPending ? t("saving") : t("rollback")}
        pending={rollback.isPending}
        onConfirm={() => rollback.mutate()}
      />
    </>
  );
}

/** Restore, or delete for good after typing the template's name. */
function DeletedActions({ row }: { row: TemplateRow }) {
  const { template, kind } = row;
  const t = useTranslations();
  const queryClient = useQueryClient();

  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: deletedKey(kind) }),
      queryClient.invalidateQueries({ queryKey: activeKey(kind) })
    ]);

  const restore = useRemovalMutation({
    mutationFn: () => restoreTemplate(kind, template.id),
    refresh
  });
  const purge = useRemovalMutation({
    mutationFn: () => permanentDelete(kind, template.id),
    refresh
  });

  return (
    <div className="flex justify-end gap-2">
      {/* Busy, Restore stays enabled so it keeps focus; a second press is ignored. */}
      <Button
        variant="outline"
        size="sm"
        aria-busy={restore.isPending || undefined}
        onClick={() => restore.mutate()}
      >
        {!restore.isPending && <RotateCcw className="size-4" />} {t("restore")}
      </Button>
      <ConfirmDialog
        trigger={
          <Button variant="ghost" size="icon" aria-label={t("delete_permanently")}>
            <Trash2 className="size-4" />
          </Button>
        }
        title={t("permanent_delete_template")}
        description={t("permanent_delete_warning")}
        confirmLabel={purge.isPending ? t("deleting") : t("delete_permanently")}
        confirmValue={template.name}
        confirmValueLabel={t("permanent_delete_type_to_confirm", { word: template.name })}
        pending={purge.isPending}
        onConfirm={() => purge.mutateAsync()}
      >
        <Banner
          status="error"
          title={template.name}
          description={t("permanent_delete_cannot_undo")}
        />
      </ConfirmDialog>
    </div>
  );
}

/**
 * One tab's list: a filter over name, category, input type and type, and a
 * table whose headers sort it (the Svelte resource tables' filter and sort
 * plugins). Rows keep the API's order until a header is chosen.
 */
function TemplateListView({
  rows,
  label,
  columns,
  emptyTitle,
  toolbarEnd
}: {
  rows: TemplateRow[];
  label: string;
  columns: TableColumn<TemplateRow>[];
  emptyTitle: string;
  toolbarEnd?: ReactNode;
}) {
  const t = useTranslations();
  const collator = useCollator();
  const compare = useMemo(() => comparators(collator.compare), [collator]);
  const searchRef = useRef<HTMLInputElement>(null);
  const [search, setSearch] = useState("");
  const filtered = useMemo(
    () => rows.filter((row) => matchesSearch(row.search, search)),
    [rows, search]
  );
  const { sortedData, sortConfig } = useTableSortableState<TemplateRow, SortKey>({
    data: filtered,
    comparators: compare
  });
  const sort = useTableSortable<TemplateRow, SortKey>(sortConfig);
  const filterLabel = t("ui_filter_items", { resourceName: label });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {rows.length > 0 ? (
          <ResourceFilterInput
            inputRef={searchRef}
            value={search}
            onChange={setSearch}
            label={filterLabel}
            placeholder={filterLabel}
            resultCount={filtered.length}
          />
        ) : (
          <span />
        )}
        {toolbarEnd}
      </div>
      {rows.length === 0 ? (
        <EmptyState title={emptyTitle} />
      ) : filtered.length === 0 ? (
        <EmptyState
          title={t("no_results_found")}
          actions={
            <AstryxButton
              label={t("clear")}
              onClick={() => {
                setSearch("");
                searchRef.current?.focus();
              }}
            />
          }
        />
      ) : (
        <div className="border-ax-border bg-ax-card rounded-ax-container [&_thead_tr]:bg-ax-sunken overflow-hidden border">
          {/* Below its min width the table scrolls inside its own named region. */}
          <Table
            data={sortedData}
            columns={columns}
            idKey="id"
            hasHover
            aria-label={label}
            plugins={{ sort }}
            className="min-w-200"
          />
        </div>
      )}
    </div>
  );
}

function ActiveTemplates({
  kind,
  templates,
  label,
  onCreate,
  onEdit
}: {
  kind: TemplateKind;
  templates: TemplateData[];
  label: string;
  onCreate: () => void;
  onEdit: (row: TemplateRow) => void;
}) {
  const t = useTranslations();
  const rows = useMemo(
    () => templates.map((template) => toRow(kind, template, t)),
    [kind, templates, t]
  );
  const columns: TableColumn<TemplateRow>[] = [
    {
      key: "name",
      header: t("template_name"),
      width: proportional(3),
      sortable: true,
      renderCell: (row) => <TemplateNameCell template={row.template} showDefault />
    },
    {
      key: "category",
      header: t("category"),
      width: proportional(1),
      sortable: true,
      renderCell: (row) => <CategoryBadge category={row.category} />
    },
    ...(kind === "apps"
      ? [
          {
            key: "input_type",
            header: t("input_type"),
            width: proportional(1.5),
            sortable: true,
            renderCell: (row: TemplateRow) => <InputTypeCell row={row} />
          }
        ]
      : []),
    {
      key: "model",
      header: t("completion_model"),
      width: proportional(1.5),
      renderCell: (row) => (
        <span className="text-ax-text-secondary">{row.template.completion_model_name ?? "—"}</span>
      )
    },
    {
      key: "usage",
      header: t("usage"),
      width: pixel(130),
      sortable: true,
      renderCell: (row) => <UsageCell count={row.template.usage_count ?? 0} />
    },
    {
      key: "created",
      header: t("created_date"),
      width: pixel(170),
      sortable: true,
      renderCell: (row) => <DateCell value={row.template.created_at} />
    },
    {
      key: "actions",
      header: <VisuallyHidden>{t("actions")}</VisuallyHidden>,
      width: pixel(64),
      align: "end",
      renderCell: (row) => <TemplateActions row={row} onEdit={onEdit} />
    }
  ];

  return (
    <TemplateListView
      rows={rows}
      label={label}
      columns={columns}
      emptyTitle={t("no_templates_found")}
      toolbarEnd={
        <AstryxButton
          variant="primary"
          label={t("new_template")}
          icon={<Plus aria-hidden="true" />}
          onClick={onCreate}
        />
      }
    />
  );
}

function DeletedTemplates() {
  const t = useTranslations();
  const assistants = useQuery(deletedAssistantTemplatesQueryOptions(browserApi));
  const apps = useQuery(deletedAppTemplatesQueryOptions(browserApi));
  const rows = useMemo(
    () => [
      ...(assistants.data ?? []).map((template) =>
        toRow("assistants", template, t, `assistants-${template.id}`)
      ),
      ...(apps.data ?? []).map((template) => toRow("apps", template, t, `apps-${template.id}`))
    ],
    [assistants.data, apps.data, t]
  );
  const columns: TableColumn<TemplateRow>[] = [
    {
      key: "name",
      header: t("template_name"),
      width: proportional(3),
      sortable: true,
      renderCell: (row) => <TemplateNameCell template={row.template} showDefault={false} />
    },
    {
      key: "type",
      header: t("type"),
      width: proportional(1),
      sortable: true,
      renderCell: (row) => row.typeLabel
    },
    {
      key: "category",
      header: t("category"),
      width: proportional(1),
      sortable: true,
      renderCell: (row) => <CategoryBadge category={row.category} />
    },
    {
      key: "deleted",
      header: t("deleted_date"),
      width: pixel(170),
      sortable: true,
      renderCell: (row) => <DateCell value={row.template.deleted_at} />
    },
    {
      key: "actions",
      header: <VisuallyHidden>{t("actions")}</VisuallyHidden>,
      width: pixel(176),
      align: "end",
      renderCell: (row) => <DeletedActions row={row} />
    }
  ];

  return (
    <QueryStateBoundary queries={[assistants, apps]} rows={2}>
      {() => (
        <TemplateListView
          rows={rows}
          label={t("deleted_templates")}
          columns={columns}
          emptyTitle={t("no_deleted_templates")}
        />
      )}
    </QueryStateBoundary>
  );
}

function TemplatesAdmin() {
  const t = useTranslations();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const { data: assistantTemplates } = useSuspenseQuery(assistantTemplatesQueryOptions(browserApi));
  const { data: appTemplates } = useSuspenseQuery(appTemplatesQueryOptions(browserApi));

  // null = closed; { kind, template? } = open (template absent → create).
  const [editor, setEditor] = useState<{
    kind: TemplateKind;
    template?: TemplateData;
  } | null>(null);
  const edit = (row: TemplateRow) => setEditor({ kind: row.kind, template: row.template });

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
      <PageHeader title={t("templates")} headingRef={headingRef} />
      {/* A removed row's focus goes to the heading. */}
      <RemovalFocusScope target={headingRef}>
        <Tabs defaultValue="assistants">
          <TabsList>
            <TabsTrigger value="assistants">{t("assistants")}</TabsTrigger>
            <TabsTrigger value="apps">{t("apps")}</TabsTrigger>
            <TabsTrigger value="deleted">{t("deleted_templates")}</TabsTrigger>
          </TabsList>
          <TabsContent value="assistants" className="pt-4">
            <ActiveTemplates
              kind="assistants"
              templates={assistantTemplates}
              label={t("assistants")}
              onCreate={() => setEditor({ kind: "assistants" })}
              onEdit={edit}
            />
          </TabsContent>
          <TabsContent value="apps" className="pt-4">
            <ActiveTemplates
              kind="apps"
              templates={appTemplates}
              label={t("apps")}
              onCreate={() => setEditor({ kind: "apps" })}
              onEdit={edit}
            />
          </TabsContent>
          <TabsContent value="deleted" className="pt-4">
            <DeletedTemplates />
          </TabsContent>
        </Tabs>
      </RemovalFocusScope>

      {editor && (
        <TemplateEditorDialog
          key={editor.template?.id ?? `new-${editor.kind}`}
          kind={editor.kind}
          template={editor.template}
          open
          onOpenChange={(open) => {
            if (!open) setEditor(null);
          }}
        />
      )}
    </div>
  );
}

/**
 * Template administration: create and edit assistant and app templates, mark
 * one as the featured default, soft-delete, and restore or permanently remove
 * deleted ones. Only while the organisation uses templates: otherwise it sends
 * the admin to /admin, as the Svelte admin/templates layout does.
 */
export function TemplatesPage() {
  const { settings } = useAppContext();
  const router = useRouter();
  const enabled = settings.using_templates === true;

  useEffect(() => {
    if (!enabled) router.replace("/admin");
  }, [enabled, router]);

  return enabled ? <TemplatesAdmin /> : null;
}
