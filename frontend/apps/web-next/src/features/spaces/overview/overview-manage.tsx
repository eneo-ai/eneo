"use client";

import { List, ListItem } from "@astryxdesign/core/List";
import { ChevronRight, Settings2, Sparkles, Users, Webhook, type LucideIcon } from "lucide-react";
import { useId } from "react";
import { useTranslations } from "use-intl";
import { phoneSections, spaceSections, type SpaceSectionId } from "../frame/space-sections";
import { useSpace } from "../use-space";
import { OverviewSection } from "./overview-section";

const ICONS: Partial<Record<SpaceSectionId, LucideIcon>> = {
  members: Users,
  settings: Settings2,
  skills: Sparkles,
  services: Webhook
};

/**
 * "Hantera ytan" on a phone (decision 24): what manages the space, which a
 * phone has no tabs for, as rows that open its screens. Only what the user
 * may manage, and nothing where there is nothing (a viewer).
 */
export function OverviewManage() {
  const t = useTranslations();
  const id = useId();
  const { space, routeId, can } = useSpace();
  const { manage } = phoneSections(spaceSections(space, can, routeId));
  if (manage.length === 0) return null;

  return (
    <OverviewSection id={id} title={t("space_manage")}>
      <List hasDividers edgeCompensation="inline">
        {manage.map((section) => {
          const Icon = ICONS[section.id];
          return (
            <ListItem
              key={section.id}
              href={section.href}
              label={
                <>
                  {t(section.id)}
                  {section.count === undefined ? null : (
                    <span className="sr-only"> ({section.count})</span>
                  )}
                </>
              }
              className="min-h-14"
              startContent={
                Icon ? (
                  <Icon aria-hidden="true" className="text-ax-text-secondary size-5" />
                ) : undefined
              }
              endContent={
                <span
                  aria-hidden="true"
                  className="text-ax-text-secondary flex items-center gap-1 text-sm tabular-nums"
                >
                  {section.count}
                  <ChevronRight className="size-4" />
                </span>
              }
            />
          );
        })}
      </List>
    </OverviewSection>
  );
}
