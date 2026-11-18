import { Tab, TabList } from "@astryxdesign/core/TabList";
import { useTranslations } from "use-intl";
import type { SpaceSection, SpaceSectionId } from "./space-sections";

// Links navigate; the TabList only needs the value to mark the current tab.
function ignoreSelection() {}

/**
 * The space's sections as an Astryx TabList in its navigation pattern: a named
 * <nav> of links, the current one marked with aria-current. Counts sit after
 * the label and are read with it: the name is what the tab shows
 * ("Assistenter 3"), so it holds the visible label (WCAG 2.5.3). On a
 * phone the strip is narrower than its tabs: Astryx scrolls it with edge
 * fades, keeps the current tab in view and moves through it with the arrow
 * keys; `globals.css` (section 12) adds scroll snapping to the tabs.
 */
export function SpaceTabs({
  sections,
  activeSection,
  showCounts = true,
  className
}: {
  sections: SpaceSection[];
  activeSection: SpaceSectionId | null;
  /** Off on a phone, where the four content tabs fit only without them. */
  showCounts?: boolean;
  className?: string;
}) {
  const t = useTranslations();

  if (sections.length === 0) return null;

  return (
    <TabList
      value={activeSection ?? ""}
      onChange={ignoreSelection}
      size="lg"
      overflow="scroll"
      aria-label={t("space_sections_label")}
      className={className}
    >
      {sections.map((section) => {
        const label = t(section.id);
        const count = showCounts ? section.count : undefined;
        return (
          <Tab
            key={section.id}
            value={section.id}
            href={section.href}
            label={label}
            endContent={
              count === undefined ? undefined : (
                <>
                  {" "}
                  <span className="text-xs font-medium tabular-nums">{count}</span>
                </>
              )
            }
          />
        );
      })}
    </TabList>
  );
}
