"use client";

import { queryOptions, useSuspenseQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { PageHeader } from "@/components/composites/page-header";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { browserApi, type EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { formatBytes } from "@/lib/format";
import type { Schema } from "@/lib/api/models";

type TokenUsage = Schema<"TokenUsageSummary">;
type StorageModel = Schema<"StorageModel">;
type StorageInfo = Schema<"StorageInfoModel">;

const NUMBER = new Intl.NumberFormat("sv-SE");

export function tokenUsageQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ["admin-token-usage"],
    queryFn: (): Promise<TokenUsage> => unwrap(api.GET("/api/v1/token-usage/"))
  });
}
export function storageQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ["admin-storage"],
    queryFn: (): Promise<StorageModel> => unwrap(api.GET("/api/v1/storage/"))
  });
}
export function storageSpacesQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ["admin-storage-spaces"],
    queryFn: (): Promise<StorageInfo> => unwrap(api.GET("/api/v1/storage/spaces/"))
  });
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card className="flex flex-col gap-1 p-4">
      <span className="text-muted-foreground text-sm">{label}</span>
      <span className="text-2xl font-semibold tabular-nums">{value}</span>
    </Card>
  );
}

function TokensTab() {
  const t = useTranslations();
  const { data } = useSuspenseQuery(tokenUsageQueryOptions(browserApi));

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label={t("usage_total_tokens")} value={NUMBER.format(data.total_token_usage)} />
        <Stat label={t("input")} value={NUMBER.format(data.total_input_token_usage)} />
        <Stat label={t("output")} value={NUMBER.format(data.total_output_token_usage)} />
      </div>
      {data.models.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("no_usage_data")}</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("model")}</TableHead>
              <TableHead className="text-right">{t("input")}</TableHead>
              <TableHead className="text-right">{t("output")}</TableHead>
              <TableHead className="text-right">{t("usage_total_tokens")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.models.map((model) => (
              <TableRow key={`${model.model_org}-${model.model_name}`}>
                <TableCell className="font-medium">{model.model_nickname}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {NUMBER.format(model.input_token_usage)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {NUMBER.format(model.output_token_usage)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {NUMBER.format(model.total_token_usage)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

function StorageTab() {
  const t = useTranslations();
  const { data: storage } = useSuspenseQuery(storageQueryOptions(browserApi));
  const { data: spaces } = useSuspenseQuery(storageSpacesQueryOptions(browserApi));

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label={t("storage_used")} value={formatBytes(storage.total_used)} />
        <Stat label={t("personal")} value={formatBytes(storage.personal_used)} />
        <Stat label={t("shared")} value={formatBytes(storage.shared_used)} />
      </div>
      {spaces.items.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("no_usage_data")}</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("name")}</TableHead>
              <TableHead className="text-right">{t("storage_used")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {spaces.items.map((space) => (
              <TableRow key={space.name}>
                <TableCell className="font-medium">{space.name}</TableCell>
                <TableCell className="text-right tabular-nums">{formatBytes(space.size)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

export function UsagePage() {
  const t = useTranslations();
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <PageHeader title={t("usage")} />
      <Tabs defaultValue="tokens">
        <TabsList>
          <TabsTrigger value="tokens">{t("tokens")}</TabsTrigger>
          <TabsTrigger value="storage">{t("storage")}</TabsTrigger>
        </TabsList>
        <TabsContent value="tokens" className="pt-4">
          <TokensTab />
        </TabsContent>
        <TabsContent value="storage" className="pt-4">
          <StorageTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
