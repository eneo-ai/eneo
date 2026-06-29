"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
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
import { type AdminModel, modelLabel, modelUsageDetailsQueryOptions } from "./models";

/** Read-only model details: properties (Info) + which resources use it (Usage). */
export function ModelDetailDialog({
  model,
  kind,
  open,
  onOpenChange
}: {
  model: AdminModel;
  kind: "completion" | "transcription";
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{modelLabel(model)}</DialogTitle>
        </DialogHeader>
        <Tabs defaultValue="info">
          <TabsList>
            <TabsTrigger value="info">{t("model_detail_tab_info")}</TabsTrigger>
            <TabsTrigger value="usage">{t("model_detail_tab_usage")}</TabsTrigger>
          </TabsList>
          <TabsContent value="info" className="pt-4">
            <InfoTab model={model} t={t} />
          </TabsContent>
          <TabsContent value="usage" className="pt-4">
            <UsageTab modelId={model.id} kind={kind} open={open} t={t} />
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}

function InfoTab({ model, t }: { model: AdminModel; t: ReturnType<typeof useTranslations> }) {
  const get = (key: string) => (model as Record<string, unknown>)[key];
  const contextWindow = get("max_input_tokens");

  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
      {model.description && (
        <div className="sm:col-span-2">
          <dt className="text-muted-foreground text-xs">{t("name")}</dt>
          <dd>{model.description}</dd>
        </div>
      )}
      {typeof get("family") === "string" && (
        <Field label={t("model_family")} value={String(get("family"))} />
      )}
      {model.hosting && <Field label={t("hosting_region")} value={model.hosting} />}
      {typeof contextWindow === "number" && (
        <Field label={t("model_context_label")} value={contextWindow.toLocaleString()} />
      )}
      <div>
        <dt className="text-muted-foreground text-xs">{t("capabilities")}</dt>
        <dd className="flex flex-wrap gap-1 pt-0.5">
          {get("vision") === true && <Badge variant="outline">{t("capability_vision")}</Badge>}
          {get("reasoning") === true && (
            <Badge variant="outline">{t("capability_reasoning")}</Badge>
          )}
        </dd>
      </div>
    </dl>
  );
}

function UsageTab({
  modelId,
  kind,
  open,
  t
}: {
  modelId: string;
  kind: "completion" | "transcription";
  open: boolean;
  t: ReturnType<typeof useTranslations>;
}) {
  const { data, isPending } = useQuery({
    ...modelUsageDetailsQueryOptions(browserApi, modelId, kind),
    enabled: open
  });

  if (isPending) return <Skeleton className="h-40 w-full" />;
  if (!data || data.items.length === 0)
    return <p className="text-muted-foreground py-4 text-sm">{t("model_usage_empty")}</p>;

  return (
    <div className="flex flex-col gap-2">
      <p className="text-muted-foreground text-xs">{t("model_usage_title")}</p>
      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("name")}</TableHead>
              <TableHead>{t("migration_impact_type")}</TableHead>
              <TableHead>{t("migration_impact_space")}</TableHead>
              <TableHead>{t("migration_impact_owner")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.items.map((entity) => (
              <TableRow key={`${entity.entity_type}-${entity.entity_id}`}>
                <TableCell className="text-sm font-medium">{entity.entity_name}</TableCell>
                <TableCell>
                  <Badge variant="secondary">{entity.entity_type}</Badge>
                </TableCell>
                <TableCell className="text-muted-foreground text-sm">
                  {entity.space_name ?? "—"}
                </TableCell>
                <TableCell className="text-muted-foreground text-sm">
                  {entity.owner_name ?? "—"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
