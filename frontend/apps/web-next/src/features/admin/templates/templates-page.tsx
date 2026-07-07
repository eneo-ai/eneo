"use client";

import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { MoreHorizontal, Pencil, Plus, RotateCcw, Star, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { EmptyState } from "@/components/composites/empty-state";
import { PageHeader } from "@/components/composites/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { cn } from "@/lib/utils";
import {
  APP_KEY,
  ASSISTANT_KEY,
  DELETED_APP_KEY,
  DELETED_ASSISTANT_KEY,
  type AppTemplate,
  type AssistantTemplate,
  appTemplatesQueryOptions,
  assistantTemplatesQueryOptions,
  deletedAppTemplatesQueryOptions,
  deletedAssistantTemplatesQueryOptions,
  rollbackAppTemplate,
  rollbackAssistantTemplate
} from "@/features/admin/templates/templates";
import { TemplateEditorDialog } from "./template-editor-dialog";

type TemplateKind = "assistants" | "apps";
type TemplateRowData = AssistantTemplate | AppTemplate;

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

function TemplateRow({
  template,
  kind,
  onEdit
}: {
  template: TemplateRowData;
  kind: TemplateKind;
  onEdit: (template: TemplateRowData) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [showDelete, setShowDelete] = useState(false);
  const [showRollback, setShowRollback] = useState(false);

  const refresh = () => queryClient.invalidateQueries({ queryKey: activeKey(kind) });

  const remove = useMutation({
    mutationFn: () => deleteTemplate(kind, template.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: activeKey(kind) });
      void queryClient.invalidateQueries({ queryKey: deletedKey(kind) });
      setShowDelete(false);
    },
    onError: (error) => toastApiError(error, t)
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
      setShowRollback(false);
    },
    onError: (error) => toastApiError(error, t)
  });
  const canRollback = Boolean(template.original_snapshot);

  return (
    <TableRow>
      <TableCell className="font-medium">
        <span className="flex items-center gap-2">
          {template.name}
          {template.is_default && (
            <Badge variant="secondary" className="gap-1">
              <Star className="size-3 fill-current" /> {t("featured")}
            </Badge>
          )}
        </span>
      </TableCell>
      <TableCell>
        <Badge variant="secondary">{template.category}</Badge>
      </TableCell>
      <TableCell className="text-muted-foreground text-sm">
        {template.completion_model_name ?? "—"}
      </TableCell>
      <TableCell className="text-muted-foreground text-right text-sm tabular-nums">
        {template.usage_count ?? 0}
      </TableCell>
      <TableCell className="w-12">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label={t("actions")}>
              <MoreHorizontal className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => onEdit(template)}>
              <Pencil className="size-4" /> {t("edit")}
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={setDefault.isPending}
              onSelect={() => setDefault.mutate(!template.is_default)}
            >
              <Star className={cn("size-4", template.is_default && "fill-current")} />
              {template.is_default ? t("remove_default") : t("set_as_default")}
            </DropdownMenuItem>
            {canRollback && (
              <DropdownMenuItem onSelect={() => setShowRollback(true)}>
                <RotateCcw className="size-4" /> {t("rollback")}
              </DropdownMenuItem>
            )}
            <DropdownMenuItem variant="destructive" onSelect={() => setShowDelete(true)}>
              <Trash2 className="size-4" /> {t("delete")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </TableCell>
      <ConfirmDialogControlled
        open={showDelete}
        onOpenChange={setShowDelete}
        title={t("delete")}
        description={t("template_delete_confirm", { name: template.name })}
        confirmLabel={remove.isPending ? t("deleting") : t("delete")}
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
      <ConfirmDialogControlled
        open={showRollback}
        onOpenChange={setShowRollback}
        title={t("rollback_template")}
        description={`${t("rollback_template_confirmation")} ${t("rollback_template_description")}`}
        confirmLabel={rollback.isPending ? t("saving") : t("rollback")}
        pending={rollback.isPending}
        onConfirm={() => rollback.mutate()}
      />
    </TableRow>
  );
}

function TemplateTable({
  templates,
  kind,
  onEdit
}: {
  templates: TemplateRowData[];
  kind: TemplateKind;
  onEdit: (template: TemplateRowData) => void;
}) {
  const t = useTranslations();
  if (templates.length === 0) return <EmptyState title={t("no_templates_found")} />;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t("name")}</TableHead>
          <TableHead>{t("category")}</TableHead>
          <TableHead>{t("completion_model")}</TableHead>
          <TableHead className="text-right">{t("uses")}</TableHead>
          <TableHead className="w-12" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {templates.map((template) => (
          <TemplateRow key={template.id} template={template} kind={kind} onEdit={onEdit} />
        ))}
      </TableBody>
    </Table>
  );
}

function DeletedRow({ template, kind }: { template: TemplateRowData; kind: TemplateKind }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [showPurge, setShowPurge] = useState(false);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: deletedKey(kind) });
    void queryClient.invalidateQueries({ queryKey: activeKey(kind) });
  };

  const restore = useMutation({
    mutationFn: () => restoreTemplate(kind, template.id),
    onSuccess: invalidate,
    onError: (error) => toastApiError(error, t)
  });
  const purge = useMutation({
    mutationFn: () => permanentDelete(kind, template.id),
    onSuccess: () => {
      invalidate();
      setShowPurge(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <TableRow>
      <TableCell className="font-medium">{template.name}</TableCell>
      <TableCell>
        <Badge variant="outline">{kind === "assistants" ? t("assistant") : t("app")}</Badge>
      </TableCell>
      <TableCell className="text-right">
        <div className="flex justify-end gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={restore.isPending}
            onClick={() => restore.mutate()}
          >
            <RotateCcw className="size-4" /> {t("restore")}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("delete_permanently")}
            disabled={purge.isPending}
            onClick={() => setShowPurge(true)}
          >
            <Trash2 className="size-4" />
          </Button>
        </div>
      </TableCell>
      <ConfirmDialogControlled
        open={showPurge}
        onOpenChange={setShowPurge}
        title={t("delete_permanently")}
        description={t("template_permanent_delete_confirm", { name: template.name })}
        confirmLabel={purge.isPending ? t("deleting") : t("delete_permanently")}
        pending={purge.isPending}
        onConfirm={() => purge.mutate()}
      />
    </TableRow>
  );
}

function DeletedTab() {
  const t = useTranslations();
  const assistants = useQuery(deletedAssistantTemplatesQueryOptions(browserApi));
  const apps = useQuery(deletedAppTemplatesQueryOptions(browserApi));

  if (assistants.isPending || apps.isPending) return <Skeleton className="h-40 w-full" />;

  const rows: { template: TemplateRowData; kind: TemplateKind }[] = [
    ...(assistants.data ?? []).map((template) => ({ template, kind: "assistants" as const })),
    ...(apps.data ?? []).map((template) => ({ template, kind: "apps" as const }))
  ];

  if (rows.length === 0) return <EmptyState title={t("no_deleted_templates")} />;

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t("name")}</TableHead>
          <TableHead>{t("type")}</TableHead>
          <TableHead className="text-right" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map(({ template, kind }) => (
          <DeletedRow key={`${kind}-${template.id}`} template={template} kind={kind} />
        ))}
      </TableBody>
    </Table>
  );
}

/**
 * Template administration: create / edit assistant & app templates, mark one
 * as the featured default, soft-delete, and restore or permanently remove
 * deleted ones.
 */
export function TemplatesPage() {
  const t = useTranslations();
  const { data: assistantTemplates } = useSuspenseQuery(assistantTemplatesQueryOptions(browserApi));
  const { data: appTemplates } = useSuspenseQuery(appTemplatesQueryOptions(browserApi));

  // null = closed; { kind, template? } = open (template absent → create).
  const [editor, setEditor] = useState<{
    kind: TemplateKind;
    template?: TemplateRowData;
  } | null>(null);

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <PageHeader title={t("templates")} />
      <Tabs defaultValue="assistants">
        <TabsList>
          <TabsTrigger value="assistants">{t("assistants")}</TabsTrigger>
          <TabsTrigger value="apps">{t("apps")}</TabsTrigger>
          <TabsTrigger value="deleted">{t("deleted_templates")}</TabsTrigger>
        </TabsList>
        <TabsContent value="assistants" className="flex flex-col gap-4 pt-4">
          <div className="flex justify-end">
            <Button size="sm" onClick={() => setEditor({ kind: "assistants" })}>
              <Plus className="size-4" /> {t("new_template")}
            </Button>
          </div>
          <TemplateTable
            templates={assistantTemplates}
            kind="assistants"
            onEdit={(template) => setEditor({ kind: "assistants", template })}
          />
        </TabsContent>
        <TabsContent value="apps" className="flex flex-col gap-4 pt-4">
          <div className="flex justify-end">
            <Button size="sm" onClick={() => setEditor({ kind: "apps" })}>
              <Plus className="size-4" /> {t("new_template")}
            </Button>
          </div>
          <TemplateTable
            templates={appTemplates}
            kind="apps"
            onEdit={(template) => setEditor({ kind: "apps", template })}
          />
        </TabsContent>
        <TabsContent value="deleted" className="pt-4">
          <DeletedTab />
        </TabsContent>
      </Tabs>

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
