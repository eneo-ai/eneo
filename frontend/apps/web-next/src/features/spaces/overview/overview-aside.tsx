"use client";

import { Avatar } from "@astryxdesign/core/Avatar";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { useCollapsible } from "@astryxdesign/core/Collapsible";
import { useCollator } from "@astryxdesign/core/i18n";
import { Icon } from "@astryxdesign/core/Icon";
import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { ChevronDown, ChevronUp } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId } from "react";
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
import { defaultModelFirst } from "./overview-data";
import { OverviewLink, OverviewSection } from "./overview-section";

const VISIBLE_MEMBERS = 4;
const VISIBLE_MODELS = 3;
const PANEL_CLASS = "border-ax-border bg-ax-card rounded-ax-container border p-4";

type ModelListItem = {
  id: string;
  name: string;
  nickname?: string | null;
  is_org_default?: boolean;
};

/**
 * A space's models, one per line. From five models on, the first three show
 * and a button opens the rest in place (hiding a single name behind a button
 * would save nothing).
 */
function ModelList({
  models,
  showAllLabel,
  showFewerLabel
}: {
  models: ModelListItem[];
  /** Accessible names of the button, starting with its visible text. */
  showAllLabel: string;
  showFewerLabel: string;
}) {
  const t = useTranslations();
  const listId = useId();
  const { isOpen, toggle } = useCollapsible({ isCollapsible: { defaultIsOpen: false } });
  const isLong = models.length > VISIBLE_MODELS + 1;
  const shown = isLong && !isOpen ? models.slice(0, VISIBLE_MODELS) : models;

  return (
    <div className="flex flex-col items-start">
      <ul id={listId} className="flex flex-col gap-1 self-stretch">
        {shown.map((model) => (
          <li key={model.id} className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <span className="min-w-0 wrap-anywhere">{modelDisplayName(model)}</span>
            {model.is_org_default ? (
              <Badge variant="blue" label={t("admin_models_default_badge")} />
            ) : null}
          </li>
        ))}
      </ul>
      {isLong ? (
        // The same button in both states, so focus stays on it. The negative
        // margin cancels the ghost button's inline padding (Astryx's edge
        // compensation), so its label lines up with the names; the top margin
        // sets it apart from them and keeps its focus ring off the last name.
        <Button
          variant="ghost"
          size="sm"
          label={isOpen ? showFewerLabel : showAllLabel}
          aria-expanded={isOpen}
          aria-controls={listId}
          onClick={toggle}
          endContent={<Icon icon={isOpen ? ChevronUp : ChevronDown} size="sm" />}
          className="-ms-3 mt-1"
        >
          {isOpen
            ? t("space_about_show_fewer")
            : t("space_about_show_all", { count: models.length })}
        </Button>
      ) : null}
    </div>
  );
}

/** "Om ytan": the space facts that exist (classification, models, creation date). */
function AboutPanel() {
  const t = useTranslations();
  const { space } = useSpace();
  const chatModels = defaultModelFirst(space.completion_models);
  const embeddingModels = space.embedding_models;
  const classification = space.security_classification?.name;
  const createdAt = space.created_at;

  if (!classification && !chatModels.length && !embeddingModels.length && !createdAt) return null;

  return (
    <OverviewSection id="overview-about" title={t("space_about_title")} className={PANEL_CLASS}>
      {/* Labels on top: model ids are long, and beside a label they would
          break into fragments in this narrow column. */}
      <MetadataList label={{ position: "top" }}>
        {classification ? (
          <MetadataListItem label={t("space_security_classification_label")}>
            <span className="font-semibold">{classification}</span>
          </MetadataListItem>
        ) : null}
        {chatModels.length ? (
          <MetadataListItem label={t("space_chat_models_label")}>
            <ModelList
              models={chatModels}
              showAllLabel={t("space_about_show_all_chat_models", { count: chatModels.length })}
              showFewerLabel={t("space_about_show_fewer_chat_models")}
            />
          </MetadataListItem>
        ) : null}
        {embeddingModels.length ? (
          <MetadataListItem label={t("space_embedding_models_label")}>
            <ModelList
              models={embeddingModels}
              showAllLabel={t("space_about_show_all_embedding_models", {
                count: embeddingModels.length
              })}
              showFewerLabel={t("space_about_show_fewer_embedding_models")}
            />
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
