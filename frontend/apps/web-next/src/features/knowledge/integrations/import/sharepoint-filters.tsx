import { Button } from "@astryxdesign/core/Button";
import { Popover } from "@astryxdesign/core/Popover";
import { Selector } from "@astryxdesign/core/Selector";
import { ListFilter, X } from "lucide-react";
import { useState } from "react";
import { useTranslations } from "use-intl";
import { TextInput } from "@/components/astryx/text-input";
import type { Schema } from "@/lib/api/models";
import { matchesSearch } from "@/lib/search";

type FilterColumn = Schema<"SharePointFilterColumn">;
export type SharePointFacets = Readonly<Record<string, string>>;
type FilterProps = {
  columns: readonly FilterColumn[];
  facets: SharePointFacets;
  onChange: (facets: SharePointFacets) => void;
};

export function SharePointFilters({ columns, facets, onChange }: FilterProps) {
  const t = useTranslations();
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const filtered = columns.filter((column) => matchesSearch([column.name, column.label], search));
  if (columns.length === 0) return null;
  return (
    <Popover
      label={t("sharepoint_filters_title")}
      isOpen={open}
      onOpenChange={setOpen}
      width={340}
      alignment="end"
      content={
        <div className="flex flex-col gap-3 p-3">
          <TextInput
            label={t("sharepoint_filters_search")}
            value={search}
            onChange={setSearch}
            hasClear
            width="100%"
          />
          <div className="flex max-h-[40dvh] flex-col gap-3 overflow-y-auto">
            {filtered.map((column) => (
              <Selector
                key={column.name}
                label={column.label}
                value={facets[column.name] ?? ""}
                width="100%"
                options={[
                  { value: "", label: t("sharepoint_filter_any") },
                  ...(column.kind === "boolean"
                    ? [
                        { value: "true", label: t("yes") },
                        { value: "false", label: t("no") }
                      ]
                    : (column.choices ?? []).map((value) => ({ value, label: value })))
                ]}
                onChange={(value) => {
                  const next = { ...facets };
                  if (value) next[column.name] = value;
                  else delete next[column.name];
                  onChange(next);
                  setOpen(false);
                }}
              />
            ))}
            {filtered.length === 0 && (
              <p className="text-ax-text-secondary text-sm">
                {t("sharepoint_filters_no_column_match")}
              </p>
            )}
          </div>
          {Object.keys(facets).length > 0 && (
            <Button
              label={t("sharepoint_filters_clear")}
              variant="ghost"
              onClick={() => onChange({})}
            />
          )}
        </div>
      }
    >
      <Button
        label={t("sharepoint_filters")}
        aria-label={t("sharepoint_filters_aria", { count: String(Object.keys(facets).length) })}
        icon={<ListFilter aria-hidden />}
        variant="secondary"
      />
    </Popover>
  );
}

export function SharePointFilterChips({ columns, facets, onChange }: FilterProps) {
  const t = useTranslations();
  if (Object.keys(facets).length === 0) return null;
  return (
    <div role="group" aria-label={t("sharepoint_filters_active")} className="flex flex-wrap gap-2">
      {Object.entries(facets).map(([name, value]) => {
        const column = columns.find((column) => column.name === name);
        const label = column?.label ?? name;
        const displayValue =
          column?.kind === "boolean" ? t(value === "true" ? "yes" : "no") : value;
        return (
          <Button
            key={name}
            size="sm"
            variant="secondary"
            label={`${label}: ${displayValue}`}
            icon={<X aria-hidden />}
            aria-label={t("sharepoint_filter_remove", { column: label })}
            onClick={() => {
              const next = { ...facets };
              delete next[name];
              onChange(next);
            }}
          />
        );
      })}
    </div>
  );
}
