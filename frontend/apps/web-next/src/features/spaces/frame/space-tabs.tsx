"use client";

import { Tab, TabList } from "@astryxdesign/core/TabList";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { SPACE_SECTION_LABEL_KEYS, type SpaceSection, type SpaceSectionId } from "./space-sections";

// Links navigate; the TabList only needs the value to mark the current tab.
function ignoreSelection() {}

/**
 * The space's sections as an Astryx TabList in its navigation pattern: a named
 * <nav> of links, the current one marked with aria-current. Counts sit after
 * the label; the accessible name spells them out ("Assistenter (3)").
 */
export function SpaceTabs({
  sections,
  activeSection,
  className
}: {
  sections: SpaceSection[];
  activeSection: SpaceSectionId | null;
  className?: string;
}) {
  const t = useTranslations();

  if (sections.length === 0) return null;

  return (
    <TabList
      value={activeSection ?? ""}
      onChange={ignoreSelection}
      size="lg"
      aria-label={t("space_sections_label")}
      // Forced colours drop the selected tab's background bar; underline it instead.
      className={cn(
        "forced-colors:[&_a[aria-current=true]]:underline forced-colors:[&_a[aria-current=true]]:underline-offset-8",
        className
      )}
    >
      {sections.map((section) => {
        const label = t(SPACE_SECTION_LABEL_KEYS[section.id]);
        const count = section.count;
        return (
          <Tab
            key={section.id}
            value={section.id}
            href={section.href}
            label={label}
            {...(count === undefined
              ? {}
              : {
                  "aria-label": t("space_section_with_count", { label, count }),
                  endContent: (
                    <span aria-hidden="true" className="text-xs font-medium tabular-nums">
                      {count}
                    </span>
                  )
                })}
          />
        );
      })}
    </TabList>
  );
}
