"use client";

import { useAnnounce } from "@astryxdesign/core/hooks";
import { useTranslations } from "next-intl";
import { useEffect, useRef } from "react";
import { PageHeader } from "@/components/composites/page-header";
import { SaveStatusIndicator } from "@/components/composites/save-status";
import { useSpaceDisplayName } from "./frame/space-header";
import { spaceLandingHref, spaceSections, type SpaceSectionId } from "./frame/space-sections";
import { useSpace } from "./use-space";

/**
 * The sticky header of an assistant, app or group-chat editor, which owns the
 * page surface (the space frame renders no header above it): a breadcrumb back
 * to the space and the tab the resource lives under, the resource's name as
 * the h1, the save state and the editor's actions ("Testa", "Klar").
 */
export function EditorHeader({
  section,
  name,
  actions
}: {
  /** The space tab the resource is listed under. */
  section: Extract<SpaceSectionId, "assistants" | "apps">;
  name: string;
  actions?: React.ReactNode;
}) {
  const t = useTranslations();
  const { space, routeId, can } = useSpace();
  const spaceName = useSpaceDisplayName();
  const sections = spaceSections(space, can, routeId);

  return (
    <PageHeader
      title={name}
      breadcrumbs={[
        { label: spaceName, href: spaceLandingHref(sections, routeId) },
        { label: t(section), href: `/spaces/${routeId}/${section}` },
        { label: name, current: true }
      ]}
      actions={
        <>
          <SaveStatusIndicator />
          {actions}
        </>
      }
      className="py-3"
    />
  );
}

/**
 * Announces "… skapades" once, for an editor that opened right after its
 * resource was created (see `useJustCreated`). Polite, so it follows the name
 * field's own announcement when the editor focuses it.
 */
export function useCreatedAnnouncement(created: boolean, message: string) {
  const announce = useAnnounce();
  const announced = useRef(false);
  useEffect(() => {
    if (!created || announced.current) return;
    announced.current = true;
    announce(message);
  }, [announce, created, message]);
}
