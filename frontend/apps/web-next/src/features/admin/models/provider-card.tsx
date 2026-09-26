"use client";

import { Button } from "@astryxdesign/core/Button";
import {
  DropdownMenu,
  DropdownMenuDivider,
  DropdownMenuItem
} from "@astryxdesign/core/DropdownMenu";
import { Heading } from "@astryxdesign/core/Heading";
import { Table, TableBody, TableHeader, TableHeaderCell, TableRow } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, Pencil, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { ProviderLogo } from "@/components/ai-elements/provider-logo";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { StatusLabel, type StatusTone } from "@/components/composites/status-label";
import type { SecurityClassification } from "@/features/admin/security-classifications/security-classifications";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import { toast } from "@/lib/toast";
import { deleteProvider, PROVIDERS_KEY } from "./model-providers";
import { ModelRow } from "./model-row";
import { MODELS_KEY } from "./models";
import { ProviderEditDialog } from "./provider-management";
import type { KindedModel, ProviderSection, ProviderStatus } from "./provider-sections";

const STATUS_TONE: Record<ProviderStatus, StatusTone> = {
  ready: "success",
  missing_key: "warning",
  inactive: "neutral"
};

function ModelTable({
  models,
  labelledBy,
  showKind,
  classifications,
  securityEnabled,
  onRemoved
}: {
  models: KindedModel[];
  labelledBy: string;
  showKind: boolean;
  classifications: SecurityClassification[];
  securityEnabled: boolean;
  onRemoved?: () => void;
}) {
  const t = useTranslations();

  // Fixed layout: every column but "Modell" has a set width, so the model
  // column takes what is left and long ids truncate instead of widening the
  // table. Below the min width the table scrolls inside its own region.
  return (
    <Table aria-labelledby={labelledBy} hasHover className="min-w-212 table-fixed">
      <TableHeader>
        <TableRow className="bg-ax-sunken [&>th]:text-xs">
          <TableHeaderCell scope="col" className="w-18">
            {t("active")}
          </TableHeaderCell>
          <TableHeaderCell scope="col">{t("model")}</TableHeaderCell>
          {showKind && (
            <TableHeaderCell scope="col" className="w-30">
              {t("type")}
            </TableHeaderCell>
          )}
          <TableHeaderCell scope="col" className="w-44">
            {t("admin_models_column_capabilities")}
          </TableHeaderCell>
          <TableHeaderCell scope="col" className="w-38 text-end">
            {t("admin_models_column_price")}
          </TableHeaderCell>
          {securityEnabled && (
            <TableHeaderCell scope="col" className="w-34">
              {t("admin_models_column_security")}
            </TableHeaderCell>
          )}
          <TableHeaderCell scope="col" className="w-14">
            <span className="sr-only">{t("actions")}</span>
          </TableHeaderCell>
        </TableRow>
      </TableHeader>
      <TableBody>
        {models.map(({ model, kind }) => (
          <ModelRow
            key={model.id}
            model={model}
            kind={kind}
            classifications={classifications}
            securityEnabled={securityEnabled}
            showKind={showKind}
            onRemoved={onRemoved}
          />
        ))}
      </TableBody>
    </Table>
  );
}

/**
 * One provider: logo, name, model count and masked key, key status, "Lägg till
 * modell" and the provider menu (edit, delete), then its models as a table.
 */
export function ProviderCard({
  section,
  models,
  showKind,
  classifications,
  securityEnabled,
  onAddModel,
  onRemoved
}: {
  section: ProviderSection;
  /** The provider's models that pass the page filters. */
  models: KindedModel[];
  showKind: boolean;
  classifications: SecurityClassification[];
  securityEnabled: boolean;
  onAddModel: (providerId: string) => void;
  /** Called after a delete removed the provider or one of its models. */
  onRemoved?: () => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const headingId = useId();
  const [showEdit, setShowEdit] = useState(false);
  const [showDelete, setShowDelete] = useState(false);

  const remove = useMutation({
    mutationFn: () => deleteProvider(browserApi, section.providerId),
    onSuccess: async () => {
      setShowDelete(false);
      toast.success(t("admin_models_provider_deleted", { name: section.name }));
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: PROVIDERS_KEY }),
        queryClient.invalidateQueries({ queryKey: MODELS_KEY })
      ]);
      onRemoved?.();
    },
    onError: (error) => toastApiError(error, t)
  });

  const statusLabel =
    section.status === "ready"
      ? t("configured")
      : section.status === "missing_key"
        ? t("key_missing")
        : t("inactive");
  const summary = [
    t("provider_model_count", { count: section.models.length }),
    section.maskedKey ? t("admin_models_provider_key", { key: section.maskedKey }) : null
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <section
      aria-labelledby={headingId}
      className="bg-ax-card border-ax-border rounded-ax-container shadow-ax-low overflow-hidden border"
    >
      <div className="border-ax-border flex flex-wrap items-center gap-x-3 gap-y-2 border-b py-3 ps-4 pe-2.5">
        <span className="bg-ax-muted rounded-ax-inner flex size-8 shrink-0 items-center justify-center">
          <ProviderLogo provider={section.providerType} className="size-5" />
        </span>
        <div className="flex min-w-0 flex-col">
          <Heading level={2} id={headingId} className="text-base break-words">
            {section.name}
          </Heading>
          <Text type="supporting">{summary}</Text>
        </div>
        <StatusLabel status={STATUS_TONE[section.status]} label={statusLabel} />
        <div className="ms-auto flex items-center gap-1">
          <Button
            size="sm"
            label={t("add_model")}
            aria-label={t("admin_models_add_model_to", { name: section.name })}
            icon={<Plus className="size-4" aria-hidden="true" />}
            onClick={() => onAddModel(section.providerId)}
          />
          <DropdownMenu
            button={{
              label: t("admin_models_provider_menu", { name: section.name }),
              tooltip: t("admin_models_provider_menu", { name: section.name }),
              icon: <MoreHorizontal className="size-4" aria-hidden="true" />,
              isIconOnly: true,
              variant: "ghost",
              size: "sm"
            }}
            hasChevron={false}
            alignment="end"
          >
            <DropdownMenuItem
              icon={Pencil}
              label={t("edit_provider")}
              onClick={() => setShowEdit(true)}
            />
            <DropdownMenuDivider />
            <DropdownMenuItem
              icon={Trash2}
              label={t("delete_provider")}
              variant="destructive"
              onClick={() => setShowDelete(true)}
            />
          </DropdownMenu>
        </div>
      </div>

      <ModelTable
        models={models}
        labelledBy={headingId}
        showKind={showKind}
        classifications={classifications}
        securityEnabled={securityEnabled}
        onRemoved={onRemoved}
      />

      <ProviderEditDialog provider={section.provider} open={showEdit} onOpenChange={setShowEdit} />
      <ConfirmDialogControlled
        open={showDelete}
        onOpenChange={setShowDelete}
        title={t("delete_provider")}
        description={`${t("delete_provider_confirm", { name: section.name })} ${t("delete_provider_warning")}`}
        confirmLabel={t("delete")}
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </section>
  );
}
