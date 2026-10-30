"use client";

import { BreadcrumbItem, Breadcrumbs } from "@astryxdesign/core/Breadcrumbs";
import { Button } from "@astryxdesign/core/Button";
import { Heading } from "@astryxdesign/core/Heading";
import { useQuery } from "@tanstack/react-query";
import { Building2, SquarePen, User } from "lucide-react";
import { useTranslations } from "use-intl";
import { ClassificationToken } from "@/components/composites/classification-token";
import { iconUrl } from "@/components/composites/icon-field";
import { useAppContext } from "@/components/providers/app-context";
import { EntityAvatar } from "@/components/composites/entity-avatar";
import { browserApi } from "@/lib/api/browser";
import { cn } from "@/lib/utils";
import { flowsListQueryOptions } from "@/features/flows/flows-api";
import { AddMemberDialog } from "../members/space-members";
import { MemberStack } from "../members/member-stack";
import { useSpace } from "../use-space";
import {
  spaceLandingHref,
  spaceSections,
  type SpaceRoute,
  type SpaceSection
} from "./space-sections";
import { SpaceTabs } from "./space-tabs";

/** The space's display name: personal and organization spaces use their alias. */
export function useSpaceDisplayName(): string {
  const t = useTranslations();
  const { space } = useSpace();
  if (space.personal) return t("personal");
  if (space.organization) return t("organization");
  return space.name;
}

/**
 * The space's tabs for this user, flows included when the tenant has them. The
 * other counts come with the space; the flows are listed separately (the same
 * list the flows tab shows), so their count arrives once that list is read.
 */
export function useSpaceSections(): SpaceSection[] {
  const { space, routeId, can } = useSpace();
  const { featureFlags } = useAppContext();
  const showsFlows = featureFlags.flows && !space.organization && can("read", "app");
  const flows = useQuery({
    ...flowsListQueryOptions(browserApi, space.id),
    enabled: showsFlows
  });
  return spaceSections(space, can, routeId, {
    flows: featureFlags.flows,
    flowCount: flows.data?.length
  });
}

/**
 * The header above every space page except the chat: breadcrumbs, the space
 * tile and name, its security classification and description, members and
 * the primary actions, then the section tabs. On a tab's own page the name is
 * the page's h1; below a tab (details, editors) the page brings its own h1 and
 * the name is a small label, so it doesn't compete with that heading.
 */
export function SpaceHeader({
  route,
  className
}: {
  route: Extract<SpaceRoute, { kind: "page" }>;
  className?: string;
}) {
  const t = useTranslations();
  const { space, routeId, can } = useSpace();
  const name = useSpaceDisplayName();
  const sections = useSpaceSections();
  const isHeading = route.isSectionRoot;
  const isShared = !space.personal && !space.organization;
  const description = space.personal
    ? t("personal_space_description")
    : space.description?.trim() || null;
  const classification = space.security_classification;
  const icon = iconUrl(space.icon_id);

  const showMembers = isShared && can("read", "member") && space.members.items.length > 0;
  // The members tab has the same "Lägg till medlem" button in its own header.
  const canAddMember = isShared && can("add", "member") && route.section !== "members";
  const canChat =
    !space.organization && space.default_assistant != null && can("read", "default_assistant");
  const isOverview = route.section === "overview" && route.isSectionRoot;

  return (
    <header className={cn("border-ax-border flex flex-col gap-4 border-b px-6 pt-5", className)}>
      <Breadcrumbs variant="supporting">
        <BreadcrumbItem href="/spaces/list" isCurrent={false}>
          {t("spaces")}
        </BreadcrumbItem>
        {isOverview ? (
          <BreadcrumbItem isCurrent>{name}</BreadcrumbItem>
        ) : (
          <BreadcrumbItem href={spaceLandingHref(sections, routeId)} isCurrent={false}>
            {name}
          </BreadcrumbItem>
        )}
      </Breadcrumbs>

      <div className="flex flex-wrap items-start gap-x-4 gap-y-3">
        <div className="flex min-w-0 flex-[1_1_20rem] items-start gap-4">
          <EntityAvatar
            name={name}
            id={space.id}
            src={icon}
            icon={
              space.personal ? (
                <User aria-hidden="true" />
              ) : space.organization ? (
                <Building2 aria-hidden="true" />
              ) : undefined
            }
            size={isHeading ? "xl" : "md"}
            className={isHeading ? "size-12 text-lg [&_svg]:size-6" : undefined}
          />
          <div className={cn("flex min-w-0 flex-1 flex-col gap-1", !isHeading && "self-center")}>
            <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
              {isHeading ? (
                <Heading
                  level={1}
                  weight="bold"
                  className="text-2xl leading-tight font-bold tracking-tight break-words"
                >
                  {name}
                </Heading>
              ) : (
                <p className="text-ax-text text-sm font-semibold break-words">{name}</p>
              )}
              <ClassificationToken name={classification?.name} />
            </div>
            {description && route.isSectionRoot ? (
              <p className="text-ax-text-secondary max-w-prose text-sm">{description}</p>
            ) : null}
          </div>
        </div>

        {showMembers || canAddMember || canChat ? (
          <div className="flex flex-wrap items-center gap-2.5">
            {showMembers ? <MemberStack members={space.members.items} /> : null}
            {canAddMember ? <AddMemberDialog variant="header" /> : null}
            {canChat ? (
              <Button
                label={t("space_new_chat")}
                variant="primary"
                href={`/spaces/${routeId}/chat`}
                icon={<SquarePen aria-hidden="true" />}
              />
            ) : null}
          </div>
        ) : null}
      </div>

      <SpaceTabs sections={sections} activeSection={route.section} className="-mb-px" />
    </header>
  );
}
