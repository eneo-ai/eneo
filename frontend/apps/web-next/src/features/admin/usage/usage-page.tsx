"use client";

import { useQuery, useSuspenseQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useMemo } from "react";
import { PageHeader } from "@/components/composites/page-header";
import { Card } from "@/components/ui/card";
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
import { formatBytes } from "@/lib/format";
import { adminModelsQueryOptions } from "@/features/admin/models/models";
import {
  buildRateMap,
  estimateCost,
  formatCost,
  storageQueryOptions,
  storageSpacesQueryOptions,
  tokenUsageQueryOptions,
  userTokenUsageQueryOptions,
  type UserTokenUsage
} from "@/features/admin/usage/usage";

const NUMBER = new Intl.NumberFormat("sv-SE");

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

function userCost(
  user: UserTokenUsage["users"][number],
  rates: ReturnType<typeof buildRateMap>
): number | null {
  let total: number | null = null;
  for (const model of user.models_used) {
    const cost = estimateCost(
      model.input_token_usage,
      model.output_token_usage,
      rates.get(model.model_id)
    );
    if (cost != null) total = (total ?? 0) + cost;
  }
  return total;
}

function UsersTab() {
  const t = useTranslations();
  const { data, isPending } = useQuery(userTokenUsageQueryOptions(browserApi));
  const { data: models } = useQuery(adminModelsQueryOptions(browserApi));
  const rates = useMemo(() => buildRateMap(models?.completion_models ?? []), [models]);

  if (isPending || !data) return <Skeleton className="h-64 w-full" />;

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label={t("resource_users")} value={NUMBER.format(data.total_users)} />
        <Stat label={t("usage_total_tokens")} value={NUMBER.format(data.total_tokens)} />
        <Stat label={t("requests")} value={NUMBER.format(data.total_requests)} />
      </div>
      {data.users.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("no_user_token_usage_data")}</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("user")}</TableHead>
              <TableHead className="text-right">{t("input_tokens")}</TableHead>
              <TableHead className="text-right">{t("output_tokens")}</TableHead>
              <TableHead className="text-right">{t("total_tokens")}</TableHead>
              <TableHead className="text-right">{t("requests")}</TableHead>
              <TableHead className="text-right">{t("estimated_cost")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.users.map((user) => (
              <TableRow key={user.user_id}>
                <TableCell className="font-medium">{user.username || user.email}</TableCell>
                <TableCell className="text-right tabular-nums">
                  {NUMBER.format(user.total_input_tokens)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {NUMBER.format(user.total_output_tokens)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {NUMBER.format(user.total_tokens)}
                </TableCell>
                <TableCell className="text-right tabular-nums">
                  {NUMBER.format(user.total_requests)}
                </TableCell>
                <TableCell className="text-muted-foreground text-right tabular-nums">
                  {formatCost(userCost(user, rates))}
                </TableCell>
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
          <TabsTrigger value="users">{t("resource_users")}</TabsTrigger>
          <TabsTrigger value="storage">{t("storage")}</TabsTrigger>
        </TabsList>
        <TabsContent value="tokens" className="pt-4">
          <TokensTab />
        </TabsContent>
        <TabsContent value="users" className="pt-4">
          <UsersTab />
        </TabsContent>
        <TabsContent value="storage" className="pt-4">
          <StorageTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
