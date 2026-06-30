"use client";

import { Search, Server, Star } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { ProviderLogo } from "@/components/ai-elements/provider-logo";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { ProviderOption } from "./model-providers";

type CapabilityFilter = "all" | "embedding" | "transcription";

const CAPABILITY_FILTERS: CapabilityFilter[] = ["all", "embedding", "transcription"];

function filterLabel(t: (key: string) => string, filter: CapabilityFilter): string {
  switch (filter) {
    case "embedding":
      return t("provider_capability_embeddings");
    case "transcription":
      return t("provider_capability_speech");
    default:
      return t("all_providers");
  }
}

function ModeBadges({ modes }: { modes: string[] }) {
  const t = useTranslations();
  const labels: string[] = [];
  if (modes.includes("completion")) labels.push(t("provider_capability_chat"));
  if (modes.includes("embedding")) labels.push(t("provider_capability_embeddings"));
  if (modes.includes("transcription")) labels.push(t("provider_capability_speech"));
  return (
    <div className="flex flex-wrap gap-1">
      {labels.map((label) => (
        <Badge key={label} variant="secondary" className="text-muted-foreground font-normal">
          {label}
        </Badge>
      ))}
    </div>
  );
}

function ProviderTile({
  option,
  favorited,
  onSelect,
  onToggleFavorite
}: {
  option: ProviderOption;
  favorited: boolean;
  onSelect: (type: string) => void;
  onToggleFavorite: (type: string) => void;
}) {
  const t = useTranslations();
  return (
    <li className="bg-card hover:border-primary/40 hover:bg-accent/30 relative rounded-xl border transition-colors">
      {/* Full-card selectable surface; the favorite toggle sits above it (z-20). */}
      <button
        type="button"
        onClick={() => onSelect(option.type)}
        aria-label={t("add_provider_named", { name: option.name })}
        className="focus-visible:ring-ring absolute inset-0 z-0 rounded-xl focus-visible:ring-2 focus-visible:outline-none"
      />
      <div className="pointer-events-none relative z-10 flex flex-col gap-2 p-3">
        <span className="bg-muted flex size-9 items-center justify-center rounded-lg">
          <ProviderLogo provider={option.type} className="size-5" />
        </span>
        <div className="min-w-0">
          <div className="truncate text-sm font-medium">{option.name}</div>
          {option.selfHosted && (
            <div className="text-muted-foreground text-xs">{t("provider_filter_self_hosted")}</div>
          )}
        </div>
        <ModeBadges modes={option.modes} />
      </div>
      <button
        type="button"
        onClick={() => onToggleFavorite(option.type)}
        aria-pressed={favorited}
        aria-label={favorited ? t("unpin_provider") : t("pin_provider")}
        className="hover:bg-accent absolute top-2 right-2 z-20 rounded-md p-1 transition-colors"
      >
        <Star
          className={cn(
            "size-4",
            favorited ? "fill-warning text-warning" : "text-muted-foreground/50"
          )}
          aria-hidden="true"
        />
      </button>
    </li>
  );
}

export function ProviderPicker({
  options,
  favorites,
  onSelect,
  onToggleFavorite
}: {
  options: ProviderOption[];
  favorites: Set<string>;
  onSelect: (type: string) => void;
  onToggleFavorite: (type: string) => void;
}) {
  const t = useTranslations();
  const [search, setSearch] = useState("");
  const [capability, setCapability] = useState<CapabilityFilter>("all");
  const [selfHostedOnly, setSelfHostedOnly] = useState(false);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return options.filter((option) => {
      if (capability !== "all" && !option.modes.includes(capability)) return false;
      if (selfHostedOnly && !option.selfHosted) return false;
      if (query && !option.name.toLowerCase().includes(query) && !option.type.includes(query)) {
        return false;
      }
      return true;
    });
  }, [options, search, capability, selfHostedOnly]);

  const favoriteOptions = filtered.filter((option) => favorites.has(option.type));
  const otherOptions = filtered.filter((option) => !favorites.has(option.type));

  return (
    <div className="flex flex-col gap-3">
      <div className="relative">
        <Search
          className="text-muted-foreground absolute top-1/2 left-2.5 size-4 -translate-y-1/2"
          aria-hidden="true"
        />
        <Input
          className="pl-8"
          placeholder={t("search_providers")}
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          aria-label={t("search_providers")}
        />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div
          className="flex items-center gap-1 rounded-lg border p-0.5"
          role="group"
          aria-label={t("capabilities")}
        >
          {CAPABILITY_FILTERS.map((filter) => (
            <button
              key={filter}
              type="button"
              onClick={() => setCapability(filter)}
              aria-pressed={capability === filter}
              className={cn(
                "rounded-md px-2.5 py-1 text-sm transition-colors",
                capability === filter
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {filterLabel(t, filter)}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => setSelfHostedOnly((value) => !value)}
          aria-pressed={selfHostedOnly}
          className={cn(
            "flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-sm transition-colors",
            selfHostedOnly
              ? "bg-accent text-accent-foreground border-accent"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          <Server className="size-3.5" aria-hidden="true" />
          {t("provider_filter_self_hosted")}
        </button>
      </div>

      {filtered.length === 0 ? (
        <p className="text-muted-foreground py-10 text-center text-sm">{t("no_providers_match")}</p>
      ) : (
        <div className="flex flex-col gap-4">
          {favoriteOptions.length > 0 && (
            <section className="flex flex-col gap-2">
              <h3 className="text-muted-foreground flex items-center gap-1.5 text-xs font-medium tracking-wide uppercase">
                <Star className="fill-warning text-warning size-3.5" aria-hidden="true" />
                {t("favorite_providers")}
              </h3>
              <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                {favoriteOptions.map((option) => (
                  <ProviderTile
                    key={option.type}
                    option={option}
                    favorited
                    onSelect={onSelect}
                    onToggleFavorite={onToggleFavorite}
                  />
                ))}
              </ul>
            </section>
          )}

          {otherOptions.length > 0 && (
            <section className="flex flex-col gap-2">
              <h3 className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
                {t("all_providers")} · {otherOptions.length}
              </h3>
              <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                {otherOptions.map((option) => (
                  <ProviderTile
                    key={option.type}
                    option={option}
                    favorited={false}
                    onSelect={onSelect}
                    onToggleFavorite={onToggleFavorite}
                  />
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
