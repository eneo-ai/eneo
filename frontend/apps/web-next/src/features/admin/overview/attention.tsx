"use client";

import { Heading } from "@astryxdesign/core/Heading";
import { List, ListItem } from "@astryxdesign/core/List";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, CircleAlert, TriangleAlert } from "lucide-react";
import { useFormatter, useTranslations } from "use-intl";
import { useId, useMemo } from "react";
import { browserApi } from "@/lib/api/browser";
import { modelDisplayName } from "@/lib/models/model-display-name";
import {
  modelProvidersQueryOptions,
  providerCapabilitiesQueryOptions
} from "@/features/admin/models/model-providers";
import { adminModelsQueryOptions } from "@/features/admin/models/models";
import { providerCardId } from "@/features/admin/models/provider-card";
import { useProviderNotices } from "@/features/admin/models/provider-notices";
import { buildProviderSections, modelsAttention } from "@/features/admin/models/provider-sections";
import { overviewCrawlerQueryOptions } from "./overview";

/** Something an admin should act on, and the page that fixes it. */
export type AttentionRow = {
  key: string;
  tone: "error" | "warning";
  label: string;
  description: string;
  href: string;
};

/**
 * What needs an admin now, from signals the product already reads (decision
 * 30): a provider whose connection test failed or whose key is missing or
 * expires within 30 days, deprecated models still in use (the models page's
 * own attention, `modelsAttention`), the crawler's errors and warnings, and
 * its scheduler. Errors first. A signal that cannot be read adds nothing:
 * the area's own page says why.
 */
export function useAdminAttention(): AttentionRow[] {
  const t = useTranslations();
  const format = useFormatter();
  const notices = useProviderNotices();
  const models = useQuery(adminModelsQueryOptions(browserApi));
  const providers = useQuery(modelProvidersQueryOptions(browserApi));
  const capabilities = useQuery(providerCapabilitiesQueryOptions(browserApi));
  const crawler = useQuery(overviewCrawlerQueryOptions(browserApi));

  const attention = useMemo(() => {
    const sections =
      models.data && providers.data && capabilities.data
        ? buildProviderSections(models.data, providers.data, capabilities.data)
        : [];
    return modelsAttention(sections, { viewerToday: notices.today });
  }, [models.data, providers.data, capabilities.data, notices.today]);

  const rows: AttentionRow[] = attention.providers.map(
    ({ section, connectionFailed, keyExpiry }) => {
      const found = [
        notices.setup(section.status),
        connectionFailed ? notices.connection(section.provider) : null,
        keyExpiry ? notices.expiryNotice(keyExpiry) : null
      ].filter((notice) => notice !== null);
      return {
        key: `provider-${section.providerId}`,
        tone: found.some((notice) => notice.tone === "error") ? "error" : "warning",
        label: section.name,
        description: found.map((notice) => notice.label).join(" · "),
        href: `/admin/models#${providerCardId(section.providerId)}`
      };
    }
  );
  if (attention.deprecated.length > 0) {
    rows.push({
      key: "deprecated-models",
      tone: "warning",
      label: t("admin_models_deprecated_title", { count: attention.deprecated.length }),
      description: t("admin_models_deprecated_description", {
        models: format.list(
          attention.deprecated.map(({ model }) => modelDisplayName(model)),
          { type: "conjunction" }
        )
      }),
      href: "/admin/models"
    });
  }
  const overview = crawler.data;
  if (overview && overview.summary.issues > 0) {
    rows.push({
      key: "crawler-issues",
      tone: "warning",
      label: t("admin_crawler_title"),
      description: t("admin_attention_crawler_issues", { count: overview.summary.issues }),
      href: "/admin/crawler"
    });
  }
  const scheduler = overview?.scheduler.status;
  if (scheduler === "degraded" || scheduler === "stale") {
    rows.push({
      key: "crawler-scheduler",
      // As the crawler's card says it: one that has not run is an error.
      tone: scheduler === "stale" ? "error" : "warning",
      label: t("admin_attention_crawler_scheduler"),
      description: t(`admin_crawler_scheduler_${scheduler}`),
      href: "/admin/crawler"
    });
  }
  // A stable sort: errors first, each kind in the order above.
  return rows.sort((a, b) => Number(b.tone === "error") - Number(a.tone === "error"));
}

/**
 * "Behöver åtgärd": the overview's first section, only when something needs
 * an admin. Each row names what and why, with its severity in words for
 * assistive technology, and opens the page that fixes it.
 */
export function AttentionSection() {
  const t = useTranslations();
  const id = useId();
  const rows = useAdminAttention();
  if (rows.length === 0) return null;

  return (
    <section aria-labelledby={id} className="flex flex-col gap-2">
      <Heading level={2} id={id} className="text-lg">
        {t("admin_attention_title")}
      </Heading>
      <List hasDividers edgeCompensation="inline">
        {rows.map((row) => (
          <ListItem
            key={row.key}
            href={row.href}
            className="min-h-14"
            // Label and reason wrap: at large text a cut line would lose them.
            label={
              <span className="block break-words">
                <span className="sr-only">
                  {t(row.tone === "error" ? "admin_attention_error" : "admin_attention_warning")}
                  :{" "}
                </span>
                {row.label}
                <span className="sr-only">, </span>
              </span>
            }
            description={<span className="block break-words">{row.description}</span>}
            startContent={
              row.tone === "error" ? (
                <CircleAlert aria-hidden="true" className="text-ax-error size-5" />
              ) : (
                <TriangleAlert aria-hidden="true" className="text-ax-warning size-5" />
              )
            }
            endContent={
              <ChevronRight aria-hidden="true" className="text-ax-text-secondary size-4" />
            }
          />
        ))}
      </List>
    </section>
  );
}
