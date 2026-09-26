"use client";

import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import {
  DropdownMenu,
  DropdownMenuDivider,
  DropdownMenuItem
} from "@astryxdesign/core/DropdownMenu";
import { Heading } from "@astryxdesign/core/Heading";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { TableBody, TableHeader, TableHeaderCell, TableRow } from "@astryxdesign/core/Table";
import { Table } from "@/components/astryx/table";
import { Text } from "@astryxdesign/core/Text";
import { useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, Pencil, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { ProviderLogo } from "@/components/ai-elements/provider-logo";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { StatusLabel } from "@/components/composites/status-label";
import type { SecurityClassification } from "@/features/admin/security-classifications/security-classifications";
import { useRemovalMutation } from "@/features/spaces/removal";
import { browserApi } from "@/lib/api/browser";
import { toast } from "@/lib/toast";
import { deleteProvider, PROVIDERS_KEY } from "./model-providers";
import { ModelRow } from "./model-row";
import { MODELS_KEY } from "./models";
import { ProviderConnectionStatus } from "./provider-connection-status";
import { ProviderEditDialog } from "./provider-management";
import { useProviderNotices } from "./provider-notices";
import type { KindedModel, ProviderSection } from "./provider-sections";

/** The id of a provider's card, where the models page banner moves focus. */
export function providerCardId(providerId: string): string {
  return `provider-${providerId}`;
}

function ModelTable({
  models,
  labelledBy,
  showKind,
  classifications,
  securityEnabled
}: {
  models: KindedModel[];
  labelledBy: string;
  showKind: boolean;
  classifications: SecurityClassification[];
  securityEnabled: boolean;
}) {
  const t = useTranslations();

  // Fixed layout: every column but "Modell" has a set width, so the model
  // column takes what is left and long ids truncate instead of widening the
  // table. Below the min width the table scrolls inside its own region.
  // Each set width is also a min width (AGENTS.md → Tables).
  return (
    <Table aria-labelledby={labelledBy} hasHover className="min-w-212 table-fixed">
      <TableHeader>
        <TableRow className="bg-ax-sunken [&>th]:text-xs">
          <TableHeaderCell scope="col" className="w-18 min-w-18">
            {t("active")}
          </TableHeaderCell>
          <TableHeaderCell scope="col">{t("model")}</TableHeaderCell>
          {showKind && (
            <TableHeaderCell scope="col" className="w-30 min-w-30">
              {t("type")}
            </TableHeaderCell>
          )}
          <TableHeaderCell scope="col" className="w-44 min-w-44">
            {t("admin_models_column_capabilities")}
          </TableHeaderCell>
          <TableHeaderCell scope="col" className="w-38 min-w-38 text-end">
            {t("admin_models_column_price")}
          </TableHeaderCell>
          {securityEnabled && (
            <TableHeaderCell scope="col" className="w-34 min-w-34">
              {t("admin_models_column_security")}
            </TableHeaderCell>
          )}
          <TableHeaderCell scope="col" className="w-14 min-w-14">
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
          />
        ))}
      </TableBody>
    </Table>
  );
}

/**
 * Why a provider cannot be deleted yet: the backend refuses a provider that
 * still has models. The menu item says so too; this is what choosing it
 * anyway opens, instead of a confirmation that would fail.
 */
function DeleteBlockedDialog({
  open,
  onOpenChange,
  name,
  count
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  name: string;
  count: number;
}) {
  const t = useTranslations();
  const descriptionId = useId();
  // One way out besides Escape and the backdrop: "Stäng" (no header X).
  return (
    <Dialog isOpen={open} onOpenChange={onOpenChange} aria-describedby={descriptionId}>
      <Layout
        height="auto"
        header={<DialogHeader title={t("provider_delete_blocked_title", { name })} />}
        content={
          <LayoutContent>
            <p id={descriptionId} className="text-sm">
              {t("provider_delete_blocked_description", { count })}
            </p>
          </LayoutContent>
        }
        footer={
          <LayoutFooter>
            <div className="flex justify-end">
              <Button label={t("close")} onClick={() => onOpenChange(false)} />
            </div>
          </LayoutFooter>
        }
      />
    </Dialog>
  );
}

/**
 * One provider: logo, name, model count and masked key, a setup problem (key
 * missing, inactive), "Lägg till modell" and the provider menu (edit,
 * delete); then the connection line (latest check, key expiry, "Testa
 * anslutning") and its models as a table, or a line saying it has none yet.
 */
export function ProviderCard({
  section,
  models,
  showKind,
  classifications,
  securityEnabled,
  onAddModel
}: {
  section: ProviderSection;
  /** The provider's models that pass the page filters. */
  models: KindedModel[];
  showKind: boolean;
  classifications: SecurityClassification[];
  securityEnabled: boolean;
  onAddModel: (providerId: string) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const notices = useProviderNotices();
  const headingId = useId();
  const [showEdit, setShowEdit] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  // All of them, not only those the filters show: any one blocks a delete.
  const modelCount = section.models.length;

  // The card, its menu and the dialog go with the provider: focus moves to
  // the page's RemovalFocusScope (the tab panel) once the lists refetched.
  const remove = useRemovalMutation({
    mutationFn: () => deleteProvider(browserApi, section.providerId),
    refresh: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: PROVIDERS_KEY }),
        queryClient.invalidateQueries({ queryKey: MODELS_KEY })
      ]),
    onRemoved: () => {
      setShowDelete(false);
      toast.success(t("admin_models_provider_deleted", { name: section.name }));
    }
  });

  const summary = [
    t("provider_model_count", { count: section.models.length }),
    section.maskedKey ? t("admin_models_provider_key", { key: section.maskedKey }) : null
  ]
    .filter(Boolean)
    .join(" · ");
  // A configured provider has no setup label: its connection line says more.
  const setup = notices.setup(section.status);

  return (
    <section
      id={providerCardId(section.providerId)}
      aria-labelledby={headingId}
      // Focusable from script only: the banner's link to this provider moves
      // focus here, so the next Tab continues inside the card.
      tabIndex={-1}
      // `relative` makes the card the containing block of the table's
      // visually hidden (absolutely positioned) texts. Without one they
      // escape the clipping scroll wrapper and widen the page, which then
      // scrolls sideways at 320 px (WCAG 1.4.10).
      className="bg-ax-card border-ax-border rounded-ax-container shadow-ax-low focus-visible:outline-ring relative overflow-hidden border focus-visible:outline-2 focus-visible:outline-offset-2"
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
        {setup ? <StatusLabel status={setup.tone} label={setup.label} /> : null}
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
              // The reason is at the action, and the item stays reachable:
              // Astryx menus skip disabled items, reason and all.
              description={
                modelCount > 0
                  ? t("provider_delete_models_first", { count: modelCount })
                  : undefined
              }
              variant="destructive"
              onClick={() => setShowDelete(true)}
            />
          </DropdownMenu>
        </div>
      </div>

      <ProviderConnectionStatus provider={section.provider} />

      {modelCount === 0 ? (
        <Text type="supporting" className="block px-4 py-3">
          {t("provider_no_models")}
        </Text>
      ) : (
        <ModelTable
          models={models}
          labelledBy={headingId}
          showKind={showKind}
          classifications={classifications}
          securityEnabled={securityEnabled}
        />
      )}

      <ProviderEditDialog provider={section.provider} open={showEdit} onOpenChange={setShowEdit} />
      {modelCount > 0 ? (
        <DeleteBlockedDialog
          open={showDelete}
          onOpenChange={setShowDelete}
          name={section.name}
          count={modelCount}
        />
      ) : (
        <ConfirmDialogControlled
          open={showDelete}
          onOpenChange={setShowDelete}
          title={t("delete_provider")}
          description={`${t("delete_provider_confirm", { name: section.name })} ${t("delete_provider_warning")}`}
          confirmLabel={t("delete")}
          pending={remove.isPending}
          onConfirm={() => remove.mutate()}
        />
      )}
    </section>
  );
}
