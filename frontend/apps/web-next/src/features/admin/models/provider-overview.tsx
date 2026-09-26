"use client";

import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Link } from "@astryxdesign/core/Link";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { useQuery } from "@tanstack/react-query";
import { Plus, Search } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { flushSync } from "react-dom";
import { EmptyState } from "@/components/composites/empty-state";
import { LoadingState } from "@/components/composites/loading-state";
import { StatusLabel } from "@/components/composites/status-label";
import {
  highestFirst,
  type SecurityClassification
} from "@/features/admin/security-classifications/security-classifications";
import { browserApi } from "@/lib/api/browser";
import { modelProvidersQueryOptions, providerCapabilitiesQueryOptions } from "./model-providers";
import { useModelTypeLabel } from "./model-type-label";
import { type ModelsPresentation, modelLabel } from "./models";
import { ProviderCard, providerCardId } from "./provider-card";
import { useProviderNotices } from "./provider-notices";
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
 * One banner for everything the data says needs an admin: active providers
 * whose key is missing, whose connection check failed or whose key expires
 * within 30 days or has expired, in their cards' words, each a link that moves
 * focus to its card; and deprecated models that are still active.
 *
 * Not a live region: it is there on page load, and it changes after actions
 * that announce their own result (a connection check, a saved key), so a
 * live region would say those twice.
 */
function AttentionBanner({
  attention,
  onShowProvider
}: {
  attention: ModelsAttention;
  onShowProvider: (providerId: string) => void;
}) {
  const t = useTranslations();
  const format = useFormatter();
  const notices = useProviderNotices();
  const { providers, deprecated } = attention;
  if (providers.length === 0 && deprecated.length === 0) return null;

  const rows = providers.map(({ section, connectionFailed, keyExpiry }) => ({
    section,
    notices: [
      notices.setup(section.status),
      connectionFailed ? notices.connection(section.provider) : null,
      keyExpiry ? notices.expiryNotice(keyExpiry) : null
    ].filter((notice) => notice !== null)
  }));
  const deprecatedTitle = t("admin_models_deprecated_title", { count: deprecated.length });
  const deprecatedDescription = t("admin_models_deprecated_description", {
    models: format.list(
      deprecated.map(({ model }) => modelLabel(model)),
      { type: "conjunction" }
    )
  });

  let title: string;
  let description: React.ReactNode = null;
  if (rows.length === 0) {
    title = deprecatedTitle;
    description = deprecatedDescription;
  } else if (deprecated.length === 0) {
    title = t("provider_status_attention_title", { count: rows.length });
  } else {
    title = t("admin_models_attention_title");
    description = (
      <>
        <strong className="font-semibold">{deprecatedTitle}.</strong> {deprecatedDescription}
      </>
    );
  }

  return (
    <Banner
      // Astryx makes a warning or error banner an alert; see above.
      role={undefined}
      status={
        rows.some((row) => row.notices.some((notice) => notice.tone === "error"))
          ? "error"
          : "warning"
      }
      title={title}
      description={description}
      collapsible={false}
    >
      {rows.length > 0 ? (
        <div className="flex flex-col gap-3">
          <ul className="flex flex-col gap-2">
            {rows.map(({ section, notices: rowNotices }) => (
              <li key={section.key} className="flex flex-wrap items-center gap-x-4 gap-y-1">
                {/* A provider without models has no card to go to. */}
                {section.models.length > 0 ? (
                  <Link
                    href={`#${providerCardId(section.providerId)}`}
                    hasUnderline
                    isStandalone
                    // A 44 px target on touch (ACCESSIBILITY.md → Target size).
                    className="pointer-coarse:inline-flex pointer-coarse:min-h-11 pointer-coarse:items-center"
                    onClick={(event) => {
                      event.preventDefault();
                      onShowProvider(section.providerId);
                    }}
                  >
                    {section.name}
                  </Link>
                ) : (
                  <Text type="label">{section.name}</Text>
                )}
                {rowNotices.map((notice) => (
                  <StatusLabel key={notice.label} status={notice.tone} label={notice.label} />
                ))}
              </li>
            ))}
          </ul>
          <Text type="supporting">{t("provider_status_attention_hint")}</Text>
        </div>
      ) : null}
    </Banner>
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
  const viewerToday = useProviderNotices().today;
  const attention = useMemo(
    () => modelsAttention(sections, { viewerToday }),
    [sections, viewerToday]
  );

  // The banner's links move focus to a provider's card. When the filters
  // hide the card, they are cleared first so it is there to receive focus.
  function showProvider(providerId: string) {
    if (!rendered.some(({ section }) => section.providerId === providerId)) {
      flushSync(() => {
        setSearch("");
        setKind("all");
        setSecurityFilter("all");
      });
    }
    document.getElementById(providerCardId(providerId))?.focus();
  }

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

      <AttentionBanner attention={attention} onShowProvider={showProvider} />

      {content}
    </div>
  );
}
