"use client";

import { releases, visibleEntries } from "@eneo/whats-new";
import type { EntryArea, Locale, Release, ReleaseEntry } from "@eneo/whats-new";
import { Sparkles } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { PageHeader } from "@/components/composites/page-header";
import { useAppContext } from "@/components/providers/app-context";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  areasPresent,
  filterEntries,
  isReadRelease,
  tourEntries,
  type ReleaseFilters
} from "./release-model";
import { useTour } from "./tour-provider";
import { useWhatsNew } from "./whats-new-provider";

const typeTone = {
  new: "border-success/30 bg-success/10 text-success",
  improved: "border-primary/30 bg-primary/10 text-primary",
  fixed: "border-warning/30 bg-warning/10 text-warning"
} as const;

export function WhatsNewPage({ title }: { title: string }) {
  const t = useTranslations();
  const locale = useLocale() as Locale;
  const { can, settings } = useAppContext();
  const { seenVersion, markLatestSeen, resetState } = useWhatsNew();
  const { running, start } = useTour();
  const isAdmin = can("admin");
  const [seenAtOpen] = useState<string | null>(() => seenVersion ?? null);
  const [selectedVersion, setSelectedVersion] = useState<string | null>(
    releases[0]?.version ?? null
  );
  const [filters, setFilters] = useState<ReleaseFilters>({ area: null, showMeOnly: false });
  const [resetting, setResetting] = useState(false);
  const current = releases.find((release) => release.version === selectedVersion) ?? null;
  const entries = current ? filterEntries(current, filters, isAdmin) : [];
  const total = current ? visibleEntries(current, isAdmin).length : 0;
  const areas = current ? areasPresent(current, isAdmin) : [];

  useEffect(() => {
    void markLatestSeen();
  }, [markLatestSeen]);

  function selectRelease(release: Release) {
    setSelectedVersion(release.version);
    if (filters.area && !areasPresent(release, isAdmin).includes(filters.area)) {
      setFilters((previous) => ({ ...previous, area: null }));
    }
  }

  async function startEntries(selected: ReleaseEntry[], version: string) {
    try {
      const outcome = await start(selected, version);
      if (outcome === "unavailable") toast.info(t("whats_new_show_me_unavailable"));
    } catch {
      toast.error(t("whats_new_tour_failed"));
    }
  }

  async function resetAndReload() {
    setResetting(true);
    try {
      await resetState();
      window.location.reload();
    } catch {
      setResetting(false);
      toast.error(t("whats_new_dev_reset_failed"));
    }
  }

  function formatDate(date: string): string {
    const [year = 0, month = 1, day = 1] = date.split("-").map(Number);
    return new Intl.DateTimeFormat(locale, { dateStyle: "long" }).format(
      new Date(year, month - 1, day)
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-8 p-6">
      <PageHeader title={title} />
      <p className="text-muted-foreground">{t("whats_new_intro")}</p>
      {releases.length === 0 ? (
        <p className="text-muted-foreground flex items-center gap-2">
          <Sparkles className="size-4" />
          {t("whats_new_empty")}
        </p>
      ) : current ? (
        <>
          <section aria-labelledby="whats-new-release-picker" className="space-y-3">
            <h2 id="whats-new-release-picker" className="text-muted-foreground text-sm font-medium">
              {t("whats_new_release_picker")}
            </h2>
            <div
              role="group"
              aria-labelledby="whats-new-release-picker"
              className="flex flex-wrap gap-2"
            >
              {releases.map((release) => (
                <button
                  key={release.version}
                  type="button"
                  aria-pressed={release.version === selectedVersion}
                  onClick={() => selectRelease(release)}
                  className="hover:bg-accent aria-pressed:bg-primary aria-pressed:text-primary-foreground inline-flex min-h-9 items-center gap-2 rounded-lg border px-3 text-sm font-medium transition-colors"
                >
                  {release.version}
                  {!release.date && (
                    <span className="text-xs opacity-80">{t("whats_new_upcoming")}</span>
                  )}
                  {seenAtOpen !== null && !isReadRelease(release, seenAtOpen) && (
                    <>
                      <span aria-hidden="true" className="bg-success size-2 rounded-full" />
                      <span className="sr-only">{t("whats_new_new_for_you")}</span>
                    </>
                  )}
                </button>
              ))}
            </div>
          </section>

          <section aria-labelledby={`release-${current.version}`} className="space-y-5">
            <div className="flex flex-wrap items-center gap-3">
              <h2 id={`release-${current.version}`} className="text-xl font-semibold">
                {t("whats_new_release", { version: current.version })}
              </h2>
              <span className="text-muted-foreground text-sm">
                {current.date ? formatDate(current.date) : t("whats_new_upcoming")}
              </span>
              {seenAtOpen !== null &&
                (isReadRelease(current, seenAtOpen) ? (
                  <span className="text-muted-foreground text-xs">{t("whats_new_read")}</span>
                ) : (
                  <Badge variant="outline" className="border-success/30 bg-success/10 text-success">
                    {t("whats_new_new_for_you")}
                  </Badge>
                ))}
              {tourEntries(current, isAdmin).length > 0 && (
                <Button
                  size="sm"
                  variant={isReadRelease(current, seenAtOpen) ? "outline" : "default"}
                  className="ml-auto"
                  disabled={running}
                  onClick={() => void startEntries(tourEntries(current, isAdmin), current.version)}
                >
                  {t("whats_new_tour_start")}
                </Button>
              )}
            </div>
            {total > 0 && (
              <div
                role="group"
                aria-label={t("whats_new_filters_label")}
                className="space-y-3 border-b pb-4"
              >
                <div className="flex flex-wrap gap-2">
                  <FilterButton
                    selected={filters.area === null}
                    onClick={() => setFilters((previous) => ({ ...previous, area: null }))}
                  >
                    {t("whats_new_filter_all")}
                  </FilterButton>
                  {areas.map((area: EntryArea) => (
                    <FilterButton
                      key={area}
                      selected={filters.area === area}
                      onClick={() => setFilters((previous) => ({ ...previous, area }))}
                    >
                      {t(`whats_new_area_${area}`)}
                    </FilterButton>
                  ))}
                </div>
                <div className="flex flex-wrap items-center gap-3 text-sm">
                  <Switch
                    id="show-me-only"
                    checked={filters.showMeOnly}
                    onCheckedChange={(showMeOnly) =>
                      setFilters((previous) => ({ ...previous, showMeOnly }))
                    }
                  />
                  <label htmlFor="show-me-only">{t("whats_new_filter_show_me")}</label>
                  <span className="text-muted-foreground ml-auto text-xs" aria-live="polite">
                    {t("whats_new_count", { shown: entries.length, total })}
                  </span>
                </div>
              </div>
            )}
            {total === 0 ? (
              <p className="text-muted-foreground">{t("whats_new_empty")}</p>
            ) : entries.length === 0 ? (
              <div className="flex items-center gap-3">
                <span className="text-muted-foreground">{t("whats_new_no_match")}</span>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setFilters({ area: null, showMeOnly: false })}
                >
                  {t("whats_new_clear_filters")}
                </Button>
              </div>
            ) : null}
            <ul className="grid gap-3">
              {entries.map((entry) => (
                <li
                  id={entry.id}
                  key={entry.id}
                  className="bg-card space-y-2 rounded-lg border p-4"
                >
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <Badge variant="outline" className={typeTone[entry.type]}>
                      {t(`whats_new_type_${entry.type}`)}
                    </Badge>
                    <span className="text-muted-foreground">
                      {t(`whats_new_area_${entry.area}`)}
                    </span>
                    {entry.audience === "admin" && (
                      <span className="text-muted-foreground">· {t("whats_new_admin_only")}</span>
                    )}
                  </div>
                  <h3 className="font-medium">{entry.title[locale] ?? entry.title.en}</h3>
                  <p className="text-muted-foreground text-sm leading-relaxed">
                    {entry.body[locale] ?? entry.body.en}
                  </p>
                  {entry.showMe && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={running}
                      onClick={() => void startEntries([entry], current.version)}
                    >
                      {t("whats_new_show_me")}
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          </section>
        </>
      ) : null}
      {settings.developer_tools_available === true && (
        <div className="border-warning/40 bg-warning/5 flex flex-wrap items-center justify-between gap-3 rounded-lg border p-4">
          <div>
            <p className="text-sm font-medium">{t("whats_new_dev_title")}</p>
            <p className="text-muted-foreground text-xs">{t("whats_new_dev_description")}</p>
          </div>
          <Button
            size="sm"
            variant="outline"
            disabled={resetting}
            onClick={() => void resetAndReload()}
          >
            {t("whats_new_dev_reset")}
          </Button>
        </div>
      )}
      <a
        href="https://docs.eneo.ai/about/release-notes"
        target="_blank"
        rel="noreferrer"
        className="text-muted-foreground hover:text-foreground text-sm underline underline-offset-2"
      >
        {t("whats_new_docs_link")}
      </a>
    </div>
  );
}

function FilterButton({
  selected,
  onClick,
  children
}: {
  selected: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className="hover:bg-accent aria-pressed:bg-primary aria-pressed:text-primary-foreground rounded-full border px-3 py-1 text-xs font-medium transition-colors"
    >
      {children}
    </button>
  );
}
