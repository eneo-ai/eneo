"use client";

import { useMutation, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { MoreHorizontal, Trash2 } from "lucide-react";
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
import {
  APP_KEY,
  ASSISTANT_KEY,
  appTemplatesQueryOptions,
  assistantTemplatesQueryOptions
} from "@/features/admin/templates/templates";

type TemplateKind = "assistants" | "apps";

function deleteTemplate(kind: TemplateKind, templateId: string) {
  if (kind === "assistants") {
    return unwrap(
      browserApi.DELETE("/api/v1/admin/templates/assistants/{template_id}", {
        params: { path: { template_id: templateId } }
      })
    );
  }
  return unwrap(
    browserApi.DELETE("/api/v1/admin/templates/apps/{template_id}", {
      params: { path: { template_id: templateId } }
    })
  );
}

function TemplateRow({
  template,
  kind,
  invalidationKey
}: {
  template: { id: string; name: string; category: string; completion_model_name?: string | null };
  kind: TemplateKind;
  invalidationKey: readonly unknown[];
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [showDelete, setShowDelete] = useState(false);

  const remove = useMutation({
    mutationFn: () => deleteTemplate(kind, template.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: invalidationKey });
      setShowDelete(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <TableRow>
      <TableCell className="font-medium">{template.name}</TableCell>
      <TableCell>
        <Badge variant="secondary">{template.category}</Badge>
      </TableCell>
      <TableCell className="text-muted-foreground text-sm">
        {template.completion_model_name ?? "—"}
      </TableCell>
      <TableCell className="w-12">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label={t("actions")}>
              <MoreHorizontal className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
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
    </TableRow>
  );
}

function TemplateTable({
  templates,
  kind,
  invalidationKey
}: {
  templates: {
    id: string;
    name: string;
    category: string;
    completion_model_name?: string | null;
  }[];
  kind: TemplateKind;
  invalidationKey: readonly unknown[];
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
          <TableHead className="w-12" />
        </TableRow>
      </TableHeader>
      <TableBody>
        {templates.map((template) => (
          <TemplateRow
            key={template.id}
            template={template}
            kind={kind}
            invalidationKey={invalidationKey}
          />
        ))}
      </TableBody>
    </Table>
  );
}

/**
 * Template administration: review and remove assistant/app templates. Template
 * creation/editing (the per-kind wizard forms), featured/default toggling,
 * restore and permanent-delete are deferred (tracked in the ledger).
 */
export function TemplatesPage() {
  const t = useTranslations();
  const { data: assistantTemplates } = useSuspenseQuery(assistantTemplatesQueryOptions(browserApi));
  const { data: appTemplates } = useSuspenseQuery(appTemplatesQueryOptions(browserApi));

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <PageHeader title={t("templates")} />
      <Tabs defaultValue="assistants">
        <TabsList>
          <TabsTrigger value="assistants">{t("assistants")}</TabsTrigger>
          <TabsTrigger value="apps">{t("apps")}</TabsTrigger>
        </TabsList>
        <TabsContent value="assistants" className="pt-4">
          <TemplateTable
            templates={assistantTemplates}
            kind="assistants"
            invalidationKey={ASSISTANT_KEY}
          />
        </TabsContent>
        <TabsContent value="apps" className="pt-4">
          <TemplateTable templates={appTemplates} kind="apps" invalidationKey={APP_KEY} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
