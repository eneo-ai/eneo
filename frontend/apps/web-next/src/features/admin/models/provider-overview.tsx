"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Lock, MoreHorizontal, Pencil, Plus, Search, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { ProviderLogo } from "@/components/ai-elements/provider-logo";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { SecurityClassification } from "@/features/admin/security-classifications/security-classifications";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import { cn } from "@/lib/utils";
import { AddModelWizard } from "./add-model-wizard";
import { deleteProvider, modelProvidersQueryOptions, PROVIDERS_KEY } from "./model-providers";
import { ModelRow } from "./model-row";
import { MODELS_KEY, type ModelKind, type ModelsPresentation, modelLabel } from "./models";
import { ProviderEditDialog } from "./provider-management";
import { buildProviderSections, type KindedModel, type ProviderSection } from "./provider-sections";

type KindFilter = "all" | ModelKind;

const KIND_FILTERS: KindFilter[] = ["all", "completion", "embedding", "transcription"];

function KeyStatus({ section }: { section: ProviderSection }) {
  const t = useTranslations();
  if (section.hasKey) {
    return (
      <Badge variant="secondary" className="border-success/30 bg-success/15 text-success gap-1">
        <KeyRound className="size-3" aria-hidden="true" /> {t("configured")}
      </Badge>
    );
  }
  return (
    <Badge variant="secondary" className="border-warning/30 bg-warning/15 text-warning gap-1">
      <Lock className="size-3" aria-hidden="true" /> {t("key_missing")}
    </Badge>
  );
}

function ProviderCard({
  section,
  models,
  showKind,
  classifications,
  securityEnabled,
  onAddModel
}: {
  section: ProviderSection;
  models: KindedModel[];
  showKind: boolean;
  classifications: SecurityClassification[];
  securityEnabled: boolean;
  onAddModel: (providerId: string) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [showEdit, setShowEdit] = useState(false);
  const [showDelete, setShowDelete] = useState(false);

  const remove = useMutation({
    mutationFn: () => deleteProvider(browserApi, section.providerId ?? ""),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: PROVIDERS_KEY });
      void queryClient.invalidateQueries({ queryKey: MODELS_KEY });
      setShowDelete(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <Card className="overflow-hidden p-0">
      <div className="flex items-center gap-3 border-b px-4 py-3">
        <ProviderLogo provider={section.providerType} className="size-7 shrink-0" />
        <div className="flex min-w-0 flex-col">
          <span className="truncate font-medium">{section.name}</span>
          <span className="text-muted-foreground text-xs">
            {t("provider_model_count", { count: models.length })}
          </span>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <KeyStatus section={section} />
          <Button variant="outline" size="sm" onClick={() => onAddModel(section.providerId)}>
            <Plus className="size-4" /> {t("add_model")}
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" aria-label={t("actions")}>
                <MoreHorizontal className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => setShowEdit(true)}>
                <Pencil className="size-4" /> {t("edit_provider")}
              </DropdownMenuItem>
              <DropdownMenuItem variant="destructive" onSelect={() => setShowDelete(true)}>
                <Trash2 className="size-4" /> {t("delete")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {!section.hasKey && (
        <div className="bg-warning/10 text-warning flex items-center gap-2 px-4 py-2 text-sm">
          <Lock className="size-4 shrink-0" aria-hidden="true" />
          <span>{t("provider_locked_hint")}</span>
        </div>
      )}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-16">{t("status")}</TableHead>
            <TableHead>{t("name")}</TableHead>
            <TableHead>{t("capabilities")}</TableHead>
            {securityEnabled && <TableHead>{t("security_classification")}</TableHead>}
            <TableHead className="w-12" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {models.map(({ model, kind }: KindedModel) => (
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
    </Card>
  );
}

export function ProviderOverview({
  models,
  classifications,
  securityEnabled
}: {
  models: ModelsPresentation;
  classifications: SecurityClassification[];
  securityEnabled: boolean;
}) {
  const t = useTranslations();
  const providers = useQuery(modelProvidersQueryOptions(browserApi));

  const [search, setSearch] = useState("");
  const [kindFilter, setKindFilter] = useState<KindFilter>("all");
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardProviderId, setWizardProviderId] = useState<string | undefined>(undefined);

  const sections = useMemo(
    () => buildProviderSections(models, providers.data ?? []),
    [models, providers.data]
  );

  // Filter each provider's models by the active kind + search, then drop
  // providers that end up with nothing to show (e.g. a freshly created custom
  // provider with no models yet, or one with no models of the filtered kind).
  // Those are still reachable via the "use existing provider" wizard step.
  const renderedSections = useMemo(() => {
    const query = search.trim().toLowerCase();
    return sections
      .map((section) => {
        const nameMatches = query !== "" && section.name.toLowerCase().includes(query);
        const models = section.models.filter(({ model, kind }) => {
          if (kindFilter !== "all" && kind !== kindFilter) return false;
          if (!query || nameMatches) return true;
          return modelLabel(model).toLowerCase().includes(query);
        });
        return { section, models };
      })
      .filter((entry) => entry.models.length > 0);
  }, [sections, kindFilter, search]);

  function openAddModel(providerId: string) {
    setWizardProviderId(providerId);
    setWizardOpen(true);
  }

  function openAddProvider() {
    setWizardProviderId(undefined);
    setWizardOpen(true);
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-48 flex-1">
          <Search
            className="text-muted-foreground absolute top-1/2 left-2.5 size-4 -translate-y-1/2"
            aria-hidden="true"
          />
          <Input
            className="pl-8"
            placeholder={t("search_models_and_providers")}
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            aria-label={t("search_models_and_providers")}
          />
        </div>
        <div
          className="flex items-center gap-1 rounded-lg border p-0.5"
          role="group"
          aria-label={t("model_type")}
        >
          {KIND_FILTERS.map((filter) => (
            <button
              key={filter}
              type="button"
              onClick={() => setKindFilter(filter)}
              aria-pressed={kindFilter === filter}
              className={cn(
                "rounded-md px-2.5 py-1 text-sm transition-colors",
                kindFilter === filter
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {filter === "all" ? t("all") : t(`${filter}_models`)}
            </button>
          ))}
        </div>
        <Button onClick={openAddProvider}>
          <Plus className="size-4" /> {t("add_provider")}
        </Button>
      </div>

      {renderedSections.length === 0 ? (
        <Card className="flex flex-col items-center gap-3 p-8 text-center">
          <p className="text-muted-foreground text-sm">
            {sections.length === 0 ? t("no_providers_yet") : t("no_providers_match")}
          </p>
          {sections.length === 0 && (
            <Button onClick={openAddProvider}>
              <Plus className="size-4" /> {t("add_provider")}
            </Button>
          )}
        </Card>
      ) : (
        renderedSections.map(({ section, models: sectionModels }) => (
          <ProviderCard
            key={section.key}
            section={section}
            models={sectionModels}
            showKind={kindFilter === "all"}
            classifications={classifications}
            securityEnabled={securityEnabled}
            onAddModel={openAddModel}
          />
        ))
      )}

      <AddModelWizard
        open={wizardOpen}
        onOpenChange={setWizardOpen}
        initialProviderId={wizardProviderId}
      />
    </div>
  );
}
