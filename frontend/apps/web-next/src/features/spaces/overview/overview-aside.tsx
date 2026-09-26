"use client";

import { Avatar } from "@astryxdesign/core/Avatar";
import { useCollator } from "@astryxdesign/core/i18n";
import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { useTranslations } from "next-intl";
import { ClientTime } from "@/components/composites/client-time";
import { cn } from "@/lib/utils";
import {
  memberDisplayName,
  personToneClass,
  SPACE_ROLE_LABEL_KEYS,
  sortMembersByRole
} from "../members/member-avatar";
import { modelDisplayName } from "../space-models";
import { useSpace } from "../use-space";
import { OverviewLink, OverviewSection } from "./overview-section";

const VISIBLE_MEMBERS = 4;
const PANEL_CLASS = "border-ax-border bg-ax-card rounded-ax-container border p-4";

/** "Om ytan": the space facts that exist (classification, models, creation date). */
function AboutPanel() {
  const t = useTranslations();
  const { space } = useSpace();
  const chatModels = space.completion_models.map(modelDisplayName).join(", ");
  const embeddingModels = space.embedding_models.map(modelDisplayName).join(", ");
  const classification = space.security_classification?.name;
  const createdAt = space.created_at;

  if (!classification && !chatModels && !embeddingModels && !createdAt) return null;

  return (
    <OverviewSection id="overview-about" title={t("space_about_title")} className={PANEL_CLASS}>
      <MetadataList label={{ position: "start", width: 112 }}>
        {classification ? (
          <MetadataListItem label={t("space_security_classification_label")}>
            <span className="font-semibold">{classification}</span>
          </MetadataListItem>
        ) : null}
        {chatModels ? (
          <MetadataListItem label={t("space_chat_models_label")}>{chatModels}</MetadataListItem>
        ) : null}
        {embeddingModels ? (
          <MetadataListItem label={t("space_embedding_models_label")}>
            <span className="font-mono text-xs break-words">{embeddingModels}</span>
          </MetadataListItem>
        ) : null}
        {createdAt ? (
          <MetadataListItem label={t("created")}>
            <ClientTime value={createdAt} format="date_long" />
          </MetadataListItem>
        ) : null}
      </MetadataList>
    </OverviewSection>
  );
}

/** Up to four members, admins first, with their role; the tab has the rest. */
function MembersPanel() {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const collator = useCollator();
  const members = sortMembersByRole(space.members.items, collator.compare);

  return (
    <OverviewSection
      id="overview-members"
      title={t("members")}
      end={<span className="text-ax-text-secondary text-sm tabular-nums">{members.length}</span>}
      className={PANEL_CLASS}
    >
      {members.length > 0 ? (
        <ul className="flex flex-col gap-3">
          {members.slice(0, VISIBLE_MEMBERS).map((member) => (
            <li key={member.id} className="flex min-w-0 items-center gap-2.5">
              <Avatar
                name={memberDisplayName(member)}
                size={32}
                tooltip={false}
                aria-hidden="true"
                className={personToneClass(member.id)}
              />
              <span className="min-w-0 flex-1 text-sm font-semibold break-all">
                {memberDisplayName(member)}
              </span>
              <span
                className={cn(
                  "rounded-ax-inner shrink-0 px-2 py-0.5 text-xs font-semibold",
                  member.role === "admin"
                    ? "bg-ax-accent-muted text-ax-text-accent"
                    : "bg-ax-muted text-ax-text-secondary"
                )}
              >
                {t(SPACE_ROLE_LABEL_KEYS[member.role])}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      <OverviewLink href={`/spaces/${routeId}/members`}>{t("manage_members")}</OverviewLink>
    </OverviewSection>
  );
}

/** Right-hand column of the overview (below the content on narrow screens). */
export function OverviewAside() {
  const { space, can } = useSpace();
  const showMembers = !space.personal && !space.organization && can("read", "member");

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <AboutPanel />
      {showMembers ? <MembersPanel /> : null}
    </div>
  );
}
