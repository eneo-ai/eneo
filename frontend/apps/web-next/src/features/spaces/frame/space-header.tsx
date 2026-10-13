"use client";

import { Avatar } from "@astryxdesign/core/Avatar";
import { AvatarGroup, AvatarGroupOverflow } from "@astryxdesign/core/AvatarGroup";
import { BreadcrumbItem, Breadcrumbs } from "@astryxdesign/core/Breadcrumbs";
import { Button } from "@astryxdesign/core/Button";
import { Heading } from "@astryxdesign/core/Heading";
import { Building2, ShieldCheck, SquarePen, User } from "lucide-react";
import { useTranslations } from "next-intl";
import { iconUrl } from "@/components/composites/icon-field";
import { EntityAvatar } from "@/components/composites/entity-avatar";
import { cn } from "@/lib/utils";
import { AddMemberDialog } from "../members/space-members";
import { memberDisplayName, personToneClass } from "../members/member-avatar";
import { useSpace } from "../use-space";
import { spaceLandingHref, spaceSections, type SpaceRoute } from "./space-sections";
import { SpaceTabs } from "./space-tabs";

const VISIBLE_MEMBERS = 3;

/** The space's display name: personal and organization spaces use their alias. */
export function useSpaceDisplayName(): string {
  const t = useTranslations();
  const { space } = useSpace();
  if (space.personal) return t("personal");
  if (space.organization) return t("organization");
  return space.name;
}

function MemberStack() {
  const t = useTranslations();
  const { space } = useSpace();
  const members = space.members.items;
  const hidden = members.length - VISIBLE_MEMBERS;

  if (members.length === 0) return null;

  return (
    <AvatarGroup size={32} aria-label={t("space_members_count", { count: members.length })}>
      {members.slice(0, VISIBLE_MEMBERS).map((member) => (
        <Avatar
          key={member.id}
          name={memberDisplayName(member)}
          className={personToneClass(member.id)}
        />
      ))}
      {hidden > 0 ? <AvatarGroupOverflow count={hidden} /> : null}
    </AvatarGroup>
  );
}

/**
 * The header above every space page except the chat: breadcrumbs, the space
 * tile and name, its security classification and description, members and
 * the primary actions, then the section tabs. On a tab's own page the name is
 * the page's h1; below a tab (details, editors) the page brings its own h1 and
 * the name is a small label, so it doesn't compete with that heading.
 */
export function SpaceHeader({ route }: { route: Extract<SpaceRoute, { kind: "page" }> }) {
  const t = useTranslations();
  const { space, routeId, can } = useSpace();
  const name = useSpaceDisplayName();
  const sections = spaceSections(space, can, routeId);
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
    <header className="border-ax-border flex flex-col gap-4 border-b px-6 pt-5">
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
              {classification ? (
                <span className="bg-ax-muted text-ax-text-secondary inline-flex min-h-6 items-center gap-1.5 rounded-full px-2.5 text-xs font-semibold">
                  <ShieldCheck aria-hidden="true" className="size-3.5 shrink-0" />
                  <span className="sr-only">{t("space_security_classification_prefix")} </span>
                  {classification.name}
                </span>
              ) : null}
            </div>
            {description && route.isSectionRoot ? (
              <p className="text-ax-text-secondary max-w-prose text-sm">{description}</p>
            ) : null}
          </div>
        </div>

        {showMembers || canAddMember || canChat ? (
          <div className="flex flex-wrap items-center gap-2.5">
            {showMembers ? <MemberStack /> : null}
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
