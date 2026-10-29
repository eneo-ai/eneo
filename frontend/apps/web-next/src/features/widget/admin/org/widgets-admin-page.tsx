"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { useQuery } from "@tanstack/react-query";
import { LayoutGrid, ShieldCheck, SwatchBook } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useId } from "react";
import { PageHeader } from "@/components/composites/page-header";
import { SaveStatusIndicator, SaveStatusProvider } from "@/components/composites/save-status";
import { browserApi } from "@/lib/api/browser";
import { widgetPolicyQueryOptions, widgetTemplatesQueryOptions } from "../queries";
import { useUrlTab } from "../use-url-tab";
import { widgetOverviewQueryOptions } from "./queries";
import { TemplateList } from "./template-list";
import { WidgetOverviewList } from "./widget-overview-list";
import { WidgetPolicyForm } from "./widget-policy-form";

const TABS = ["widgets", "policy", "templates"] as const;
type TabId = (typeof TABS)[number];

function Stat({ label, value, warn = false }: { label: string; value: string; warn?: boolean }) {
  return (
    <li className="bg-ax-card border-ax-border rounded-xl border p-4">
      <p className="text-ax-text-secondary text-xs">{label}</p>
      <p className={`text-2xl font-semibold tabular-nums ${warn ? "text-ax-orange" : ""}`}>
        {value}
      </p>
    </li>
  );
}

/**
 * Admin → Webbwidgetar. Three concerns, one tab each: the organisation's
 * widgets and how they are used, the policy every widget must stay within,
 * and the templates editors start from.
 */
export function WidgetsAdminPage() {
  const t = useTranslations();
  const locale = useLocale();
  const ids = useId();
  const number = new Intl.NumberFormat(locale === "sv" ? "sv-SE" : "en-US");
  const [tab, setTab] = useUrlTab<TabId>(TABS, "widgets");

  const overview = useQuery(widgetOverviewQueryOptions(browserApi));
  const policy = useQuery(widgetPolicyQueryOptions(browserApi));
  const templates = useQuery(widgetTemplatesQueryOptions(browserApi));
  const totals = overview.data?.totals;

  const tabId = (value: TabId) => `${ids}-tab-${value}`;
  const panelId = (value: TabId) => `${ids}-panel-${value}`;
  const panel = (value: TabId, children: React.ReactNode) => (
    <div
      role="tabpanel"
      id={panelId(value)}
      aria-labelledby={tabId(value)}
      hidden={tab !== value}
      className="flex flex-col gap-6"
    >
      {children}
    </div>
  );
  const loading = <p className="text-ax-text-secondary text-sm">{t("loading")}</p>;

  return (
    <SaveStatusProvider>
      <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-6">
        <PageHeader title={t("widget_admin_nav")} actions={<SaveStatusIndicator />} />

        <TabList
          role="tablist"
          aria-label={t("widget_admin_nav")}
          value={tab}
          onChange={(next) => setTab(next as TabId)}
          hasDivider
        >
          <Tab
            id={tabId("widgets")}
            value="widgets"
            label={t("widget_admin_tab_widgets")}
            icon={<LayoutGrid aria-hidden="true" className="size-4" />}
            panelId={panelId("widgets")}
            endContent={
              totals ? <Badge variant="neutral" label={number.format(totals.widgets)} /> : undefined
            }
          />
          <Tab
            id={tabId("policy")}
            value="policy"
            label={t("widget_admin_tab_policy")}
            icon={<ShieldCheck aria-hidden="true" className="size-4" />}
            panelId={panelId("policy")}
          />
          <Tab
            id={tabId("templates")}
            value="templates"
            label={t("widget_admin_templates")}
            icon={<SwatchBook aria-hidden="true" className="size-4" />}
            panelId={panelId("templates")}
            endContent={
              templates.data ? (
                <Badge variant="neutral" label={number.format(templates.data.length)} />
              ) : undefined
            }
          />
        </TabList>

        {panel(
          "widgets",
          overview.data && totals ? (
            <>
              <p className="text-ax-text-secondary max-w-[72ch] text-sm">
                {t("widget_admin_overview_description")}
              </p>
              <ul className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <li className="bg-ax-card border-ax-border rounded-xl border p-4">
                  <p className="text-ax-text-secondary text-xs">{t("widget_admin_stat_widgets")}</p>
                  <p className="text-2xl font-semibold tabular-nums">
                    {number.format(totals.widgets)}{" "}
                    <span className="text-ax-text-secondary text-sm font-normal">
                      {totals.active === 1
                        ? t("widget_admin_stat_active_one")
                        : t("widget_admin_stat_active", { count: number.format(totals.active) })}
                    </span>
                  </p>
                </li>
                <Stat
                  label={t("widget_admin_overview_questions_30d")}
                  value={number.format(totals.questions_30d)}
                />
                <Stat
                  label={t("widget_admin_overview_tokens_30d")}
                  value={number.format(totals.tokens_30d)}
                />
                <Stat
                  label={t("widget_admin_overview_blocked_30d")}
                  value={number.format(totals.blocked_30d)}
                  warn={totals.blocked_30d > 0}
                />
              </ul>
              <WidgetOverviewList overview={overview.data} />
            </>
          ) : overview.isError ? (
            <p role="alert" className="text-ax-red text-sm">
              {t("widget_admin_overview_failed")}
            </p>
          ) : (
            loading
          )
        )}

        {panel(
          "policy",
          policy.data ? (
            <WidgetPolicyForm policy={policy.data} />
          ) : policy.data === null ? (
            <p role="alert" className="text-ax-red text-sm">
              {t("widget_admin_policy_failed")}
            </p>
          ) : (
            loading
          )
        )}

        {panel("templates", templates.data ? <TemplateList templates={templates.data} /> : loading)}
      </div>
    </SaveStatusProvider>
  );
}
