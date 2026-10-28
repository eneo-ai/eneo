"use client";

import { Button } from "@astryxdesign/core/Button";
import { Heading } from "@astryxdesign/core/Heading";
import { SquarePen } from "lucide-react";
import { useTranslations } from "next-intl";
import { ClassificationToken } from "@/components/composites/classification-token";
import { PageBar } from "@/components/shell/page-bar";
import { useSpace } from "../use-space";
import { useSpaceDisplayName } from "./space-header";
import { phoneSections, spaceLandingHref, spaceSections, type SpaceRoute } from "./space-sections";
import { SpaceTabs } from "./space-tabs";

/**
 * A space on a phone (decision 24), in place of the header with breadcrumbs.
 * A shared space is pushed from Ytor: a page bar back to Ytor and to the
 * space chat, then the name with its classification and the content tabs
 * (Översikt, Assistenter, Appar, Kunskap). What manages the space is listed
 * under "Hantera ytan" on Översikt, and opens as a screen of its own, back to
 * the space. A page below a tab goes back to that tab. The personal and
 * organisation spaces are reached from the menu, so their tabs keep the
 * shell's top bar with the menu; the organisation space has no Översikt and
 * keeps all its tabs (F4).
 *
 * A fragment: the page bar sticks to the top of the page panel, so it must
 * be a child of the frame that holds the whole page.
 */
export function SpacePhoneHeader({
  route,
  segments
}: {
  route: Extract<SpaceRoute, { kind: "page" }>;
  /** The route's segments below the space, to find a page between this one and its tab. */
  segments: readonly string[];
}) {
  const t = useTranslations();
  const { space, routeId, can } = useSpace();
  const name = useSpaceDisplayName();
  const sections = spaceSections(space, can, routeId);
  const { tabs, manage } = phoneSections(sections);
  const section = sections.find((candidate) => candidate.id === route.section) ?? null;
  const tabbed = route.isSectionRoot && tabs.some((tab) => tab.id === route.section);
  const managed = route.isSectionRoot && manage.some((item) => item.id === route.section);
  const fromMenu = space.personal || space.organization;
  const canChat =
    !space.organization && space.default_assistant != null && can("read", "default_assistant");
  const description = space.personal
    ? t("personal_space_description")
    : space.description?.trim() || null;
  const spaceHref =
    sections.find((candidate) => candidate.id === "overview")?.href ??
    spaceLandingHref(sections, routeId);

  // A result is opened from its app's page (apps/<app>/results/<result>).
  const appId = route.section === "apps" && segments[2] === "results" ? segments[1] : undefined;
  const app = space.applications?.apps.items.find((item) => item.id === appId);

  // The screen the user came down from (decision 20). A section root that is
  // neither a tab nor in Hantera ytan (the organisation space's Översikt, a
  // section the user may not open) is the space's own: a space from the menu
  // keeps the menu there, a shared space goes back to its Översikt.
  const parent = tabbed
    ? fromMenu
      ? null
      : { label: t("spaces"), href: "/spaces/list" }
    : route.isSectionRoot
      ? fromMenu && !managed
        ? null
        : { label: name, href: spaceHref }
      : app && section
        ? { label: app.name, href: `${section.href}/${app.id}` }
        : section
          ? { label: t(section.id), href: section.href }
          : { label: name, href: spaceHref };

  return (
    <>
      {parent ? (
        <PageBar
          until="md"
          parent={parent}
          title={
            tabbed ? name : route.isSectionRoot && route.section ? t(route.section) : undefined
          }
          actions={
            tabbed && canChat ? (
              <Button
                label={t("space_new_chat")}
                tooltip={t("space_new_chat")}
                isIconOnly
                variant="ghost"
                size="lg"
                href={`/spaces/${routeId}/chat`}
                icon={<SquarePen aria-hidden="true" />}
              />
            ) : undefined
          }
        />
      ) : null}
      {tabbed ? (
        <div className="border-ax-border flex flex-col gap-3 border-b pt-4 md:hidden">
          <div className="flex flex-col items-start gap-2 px-4">
            <Heading
              level={1}
              weight="bold"
              className="text-xl leading-tight font-semibold text-balance break-words"
            >
              {name}
            </Heading>
            <ClassificationToken name={space.security_classification?.name} />
            {description && route.section === "overview" ? (
              <p className="text-ax-text-secondary text-sm text-pretty">{description}</p>
            ) : null}
          </div>
          {/* px-1 and the tab's own inset start the first label on the 16 px line. */}
          <SpaceTabs
            sections={tabs}
            activeSection={route.section}
            showCounts={false}
            className="-mb-px px-1"
          />
        </div>
      ) : route.isSectionRoot ? (
        // The screen's visible title is the page's own heading ("Medlemmar").
        <div className="md:hidden">
          <Heading level={1} className="sr-only">
            {name}
          </Heading>
        </div>
      ) : null}
    </>
  );
}
