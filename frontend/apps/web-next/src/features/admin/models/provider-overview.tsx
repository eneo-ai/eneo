"use client";

import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Selector } from "@astryxdesign/core/Selector";
import { TextInput } from "@astryxdesign/core/TextInput";
import { useQuery } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { LoadingState } from "@/components/composites/loading-state";
import {
  highestFirst,
  type SecurityClassification
} from "@/features/admin/security-classifications/security-classifications";
import { browserApi } from "@/lib/api/browser";
import { modelProvidersQueryOptions, providerCapabilitiesQueryOptions } from "./model-providers";
import { useModelTypeLabel } from "./model-type-label";
import { type ModelsPresentation, modelLabel } from "./models";
import { ProviderCard } from "./provider-card";
import {
  buildProviderSections,
  countByKind,
  filterSections,
  KIND_FILTERS,
  type KindFilter,
  type ModelFilters,
  type ModelsAttention,
  modelsAttention,
  UNCLASSIFIED
} from "./provider-sections";

/**
 * One warning for everything the data says needs an admin: providers whose
 * required API key is missing, and deprecated models that are still active.
 * Rendered on page load, so it is a polite status (not an alert).
 */
function AttentionBanner({ attention }: { attention: ModelsAttention }) {
  const t = useTranslations();
  const format = useFormatter();
  const { missingKey, deprecated } = attention;
  if (missingKey.length === 0 && deprecated.length === 0) return null;

  const keyIssue =
    missingKey.length > 0
      ? {
          title: t("admin_models_missing_key_title", { count: missingKey.length }),
          description: t("admin_models_missing_key_description", {
            providers: format.list(
              missingKey.map((section) => section.name),
              { type: "conjunction" }
            )
          })
        }
      : null;
  const deprecatedIssue =
    deprecated.length > 0
      ? {
          title: t("admin_models_deprecated_title", { count: deprecated.length }),
          description: t("admin_models_deprecated_description", {
            models: format.list(
              deprecated.map(({ model }) => modelLabel(model)),
              { type: "conjunction" }
            )
          })
        }
      : null;
  const issues = [keyIssue, deprecatedIssue].filter((issue) => issue !== null);
  const single = issues.length === 1 ? issues[0] : null;

  return (
    <Banner
      role="status"
      status="warning"
      title={single ? single.title : t("admin_models_attention_title")}
      description={
        single ? (
          single.description
        ) : (
          <ul className="flex list-disc flex-col gap-1 ps-5">
            {issues.map((issue) => (
              <li key={issue.title}>
                <strong className="font-semibold">{issue.title}.</strong> {issue.description}
              </li>
            ))}
          </ul>
        )
      }
    />
  );
}

/**
 * The "Modeller" tab: search, type and security-class filters, the attention
 * banner and one card per provider with its models.
 */
export function ProviderOverview({
  models,
  classifications,
  securityEnabled,
  onAddModel,
  onAddProvider,
  onRemoved
}: {
  models: ModelsPresentation;
  classifications: SecurityClassification[];
  securityEnabled: boolean;
  onAddModel: (providerId: string) => void;
  onAddProvider: () => void;
  /** Called after a delete removed a provider or model (focus rescue). */
  onRemoved?: () => void;
}) {
  const t = useTranslations();
  const typeLabel = useModelTypeLabel();
  const announce = useAnnounce();
  const providers = useQuery(modelProvidersQueryOptions(browserApi));
  // Which provider types need an API key (static per deployment, cached).
  const capabilities = useQuery(providerCapabilitiesQueryOptions(browserApi));

  const [search, setSearch] = useState("");
  const [kind, setKind] = useState<KindFilter>("all");
  const [securityFilter, setSecurityFilter] = useState("all");
  const security = securityEnabled ? securityFilter : "all";
  const filters: ModelFilters = { search, kind, security };

  const sections = useMemo(
    () =>
      capabilities.data
        ? buildProviderSections(models, providers.data ?? [], capabilities.data)
        : [],
    [models, providers.data, capabilities.data]
  );
  const rendered = useMemo(
    () => filterSections(sections, { search, kind, security }),
    [sections, search, kind, security]
  );
  const counts = useMemo(
    () => countByKind(sections, { search, security }),
    [sections, search, security]
  );
  const attention = useMemo(() => modelsAttention(sections), [sections]);

  // The number of models a filter change leaves is announced politely,
  // without moving focus (WCAG 4.1.3).
  function announceResults(next: Partial<ModelFilters>) {
    const nextFilters = { ...filters, ...next };
    const isFiltering =
      nextFilters.search.trim() !== "" ||
      nextFilters.kind !== "all" ||
      nextFilters.security !== "all";
    const shown = filterSections(sections, nextFilters).reduce(
      (total, entry) => total + entry.models.length,
      0
    );
    announce(isFiltering ? t("admin_models_results", { count: shown }) : "");
  }

  const securityOptions = [
    { value: "all", label: t("all") },
    { value: UNCLASSIFIED, label: t("admin_models_unclassified") },
    ...highestFirst(classifications).map((classification) => ({
      value: classification.id,
      label: classification.name
    }))
  ];

  let content: React.ReactNode;
  if (providers.isError || capabilities.isError) {
    content = (
      <EmptyState
        title={t("admin_models_providers_load_failed")}
        actions={
          <Button
            label={t("retry")}
            onClick={() => {
              if (providers.isError) void providers.refetch();
              if (capabilities.isError) void capabilities.refetch();
            }}
            variant="secondary"
          />
        }
      />
    );
  } else if (providers.isPending || capabilities.isPending) {
    content = <LoadingState rows={4} />;
  } else if (rendered.length === 0) {
    content =
      sections.length === 0 ? (
        <EmptyState
          title={t("no_providers_yet")}
          actions={
            <Button
              variant="primary"
              label={t("add_provider")}
              icon={<Plus className="size-4" aria-hidden="true" />}
              onClick={onAddProvider}
            />
          }
        />
      ) : (
        <EmptyState title={t("no_providers_match")} />
      );
  } else {
    content = rendered.map(({ section, models: sectionModels }) => (
      <ProviderCard
        key={section.key}
        section={section}
        models={sectionModels}
        showKind={kind === "all"}
        classifications={classifications}
        securityEnabled={securityEnabled}
        onAddModel={onAddModel}
        onRemoved={onRemoved}
      />
    ));
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2.5">
        <TextInput
          label={t("search_models_and_providers")}
          isLabelHidden
          placeholder={t("search_models_and_providers")}
          startIcon={Search}
          value={search}
          onChange={(value) => {
            setSearch(value);
            announceResults({ search: value });
          }}
          hasClear
          className="w-full sm:w-72"
        />
        {/* Segments wrap instead of overflowing on narrow screens (1.4.10). */}
        <SegmentedControl
          label={t("model_type")}
          value={kind}
          onChange={(value) => {
            setKind(value as KindFilter);
            announceResults({ kind: value as KindFilter });
          }}
          className="max-w-full flex-wrap"
        >
          {KIND_FILTERS.map((filter) => (
            <SegmentedControlItem
              key={filter}
              value={filter}
              label={t("admin_models_kind_filter_option", {
                label: filter === "all" ? t("all") : typeLabel(filter),
                count: counts[filter]
              })}
            />
          ))}
        </SegmentedControl>
        {securityEnabled && (
          <Selector
            label={t("admin_models_security_filter")}
            isLabelHidden
            options={securityOptions}
            value={securityFilter}
            onChange={(value) => {
              setSecurityFilter(value);
              announceResults({ security: value });
            }}
            renderValue={(option) =>
              t("admin_models_filter_value", {
                label: t("admin_models_security_filter"),
                value: option.label ?? ""
              })
            }
            width="16rem"
          />
        )}
      </div>

      <AttentionBanner attention={attention} />

      {content}
    </div>
  );
}
