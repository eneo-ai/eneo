"use client";

import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { TextInput } from "@astryxdesign/core/TextInput";
import { ToggleButton } from "@astryxdesign/core/ToggleButton";
import { Token } from "@astryxdesign/core/Token";
import { Search, Server, Star } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { ProviderLogo } from "@/components/ai-elements/provider-logo";
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

function ModeTokens({ modes }: { modes: string[] }) {
  const t = useTranslations();
  const labels: string[] = [];
  if (modes.includes("completion")) labels.push(t("provider_capability_chat"));
  if (modes.includes("embedding")) labels.push(t("provider_capability_embeddings"));
  if (modes.includes("transcription")) labels.push(t("provider_capability_speech"));
  return (
    <ul className="flex flex-wrap gap-1">
      {labels.map((label) => (
        <li key={label} className="flex">
          <Token label={label} size="sm" />
        </li>
      ))}
    </ul>
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
    <li className="bg-ax-card border-ax-border hover:border-ax-border-strong hover:bg-ax-hover rounded-ax-container relative border transition-colors">
      {/* Full-card selectable surface; the favorite toggle sits above it (z-20). */}
      <button
        type="button"
        onClick={() => onSelect(option.type)}
        aria-label={t("add_provider_named", { name: option.name })}
        className="focus-visible:outline-ring rounded-ax-container absolute inset-0 z-0 focus-visible:outline-2 focus-visible:outline-offset-2"
      />
      <div className="pointer-events-none relative z-10 flex flex-col gap-2 p-3">
        <span className="bg-ax-muted rounded-ax-element flex size-9 items-center justify-center">
          <ProviderLogo provider={option.type} className="size-5" />
        </span>
        <div className="min-w-0">
          <div className="truncate text-sm font-medium">{option.name}</div>
          {option.selfHosted && (
            <div className="text-ax-text-secondary text-xs">{t("provider_filter_self_hosted")}</div>
          )}
        </div>
        <ModeTokens modes={option.modes} />
      </div>
      <div className="absolute top-2 right-2 z-20">
        {/* A toggle keeps one name; aria-pressed says whether it is pinned. */}
        <ToggleButton
          label={t("admin_models_pin_provider", { name: option.name })}
          isIconOnly
          size="sm"
          icon={<Star className="text-ax-text-secondary size-4" aria-hidden="true" />}
          pressedIcon={<Star className="fill-warning text-warning size-4" aria-hidden="true" />}
          isPressed={favorited}
          onPressedChange={() => onToggleFavorite(option.type)}
        />
      </div>
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
      <TextInput
        label={t("search_providers")}
        isLabelHidden
        placeholder={t("search_providers")}
        startIcon={Search}
        value={search}
        onChange={setSearch}
        hasClear
      />

      <div className="flex flex-wrap items-center justify-between gap-2">
        <SegmentedControl
          label={t("capabilities")}
          value={capability}
          onChange={(value) => setCapability(value as CapabilityFilter)}
          className="max-w-full flex-wrap"
        >
          {CAPABILITY_FILTERS.map((filter) => (
            <SegmentedControlItem key={filter} value={filter} label={filterLabel(t, filter)} />
          ))}
        </SegmentedControl>
        <ToggleButton
          label={t("provider_filter_self_hosted")}
          icon={<Server className="size-4" aria-hidden="true" />}
          isPressed={selfHostedOnly}
          onPressedChange={setSelfHostedOnly}
        >
          {t("provider_filter_self_hosted")}
        </ToggleButton>
      </div>

      {filtered.length === 0 ? (
        <p className="text-ax-text-secondary py-10 text-center text-sm">
          {t("no_providers_match")}
        </p>
      ) : (
        <div className="flex flex-col gap-4">
          {favoriteOptions.length > 0 && (
            <section className="flex flex-col gap-2">
              <h3 className="text-ax-text-secondary flex items-center gap-1.5 text-xs font-medium tracking-wide uppercase">
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
              <h3 className="text-ax-text-secondary text-xs font-medium tracking-wide uppercase">
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
