import { Button } from "@astryxdesign/core/Button";
import { ClickableCard } from "@astryxdesign/core/ClickableCard";
import { Heading } from "@astryxdesign/core/Heading";
import { SquarePen } from "lucide-react";
import { useTranslations } from "use-intl";
import { PageHeader } from "@/components/composites/page-header";
import { useAppContext } from "@/components/providers/app-context";
import { firstNameOf } from "@/features/chat/format";
import { useSectionHeadingLevels } from "@/features/spaces/frame/space-frame";
import { OverviewApps } from "@/features/spaces/overview/overview-apps";
import { OverviewAssistants } from "@/features/spaces/overview/overview-assistants";
import { OverviewKnowledge } from "@/features/spaces/overview/overview-knowledge";
import { OverviewManage } from "@/features/spaces/overview/overview-manage";
import { AddMemberDialog } from "@/features/spaces/members/space-members";
import { useSpace } from "@/features/spaces/use-space";
import { usePhoneScreen, useTouchTablet } from "@/lib/hooks/use-media-match";

/** A count tile, as Svelte's OverviewTile: the label and a large number, the whole card a link. */
function CountTile({ title, count, href }: { title: string; count: number; href: string }) {
  return (
    <ClickableCard label={`${title} ${count}`} href={href} padding={5} elevation="low">
      <div className="flex min-h-40 flex-col justify-between gap-6">
        <span className="font-mono text-sm uppercase">{title}</span>
        <span className="self-end text-6xl leading-none font-bold tabular-nums">{count}</span>
      </div>
    </ClickableCard>
  );
}

/**
 * The space overview, as Svelte's (`[spaceId]/overview/+page.svelte`): the
 * page title "Översikt" with the space's actions, the space's name (in the
 * personal space a greeting) and description, and a tile per kind of
 * content with its count. The tiles follow the reader's permissions.
 *
 * Svelte is not built for touch, so a phone or a tablet keeps the overview
 * #1328 built: the newest assistants, apps and knowledge, things to open with
 * a finger rather than counts that repeat the tabs. Their space header (a
 * tablet's SpaceHeader, a phone's SpacePhoneHeader) carries the name, the
 * description and Ny chatt; a phone lists what manages the space under
 * "Hantera ytan" (decision 24).
 */
export function SpaceOverview() {
  const phone = usePhoneScreen();
  const tablet = useTouchTablet();
  return phone || tablet ? <OverviewLists /> : <WideOverview />;
}

/** The newest assistants, apps and (beside the sidebar) knowledge; Hantera ytan on a phone. */
function OverviewLists() {
  const { space, can } = useSpace();
  const phone = usePhoneScreen();
  return (
    <div className="flex w-full min-w-0 flex-col gap-7">
      {!space.organization && can("read", "assistant") ? <OverviewAssistants /> : null}
      {!space.organization && can("read", "app") ? <OverviewApps /> : null}
      {/* A phone has the Kunskap tab in the space's strip: its overview lists what to act on. */}
      {!phone && (can("read", "collection") || can("read", "website")) ? (
        <OverviewKnowledge />
      ) : null}
      {phone ? <OverviewManage /> : null}
    </div>
  );
}

function CountTiles() {
  const t = useTranslations();
  const { space, can, routeId } = useSpace();
  const base = `/spaces/${routeId}`;
  const own = (item: { space_id: string }) => item.space_id === space.id;

  const tiles = [
    can("read", "assistant") && {
      title: t("assistants"),
      count: space.applications?.assistants.count ?? 0,
      href: `${base}/assistants`
    },
    can("read", "app") && {
      title: t("apps"),
      count: space.applications?.apps.count ?? 0,
      href: `${base}/apps`
    },
    can("read", "collection") && {
      title: t("collections"),
      count: space.knowledge.groups.items.filter(own).length,
      href: `${base}/knowledge?tab=collections`
    },
    can("read", "website") && {
      title: t("websites"),
      count: space.knowledge.websites.items.filter(own).length,
      href: `${base}/knowledge?tab=websites`
    },
    can("read", "member") && {
      title: t("members"),
      count: space.members.items.length,
      href: `${base}/members`
    }
  ].filter((tile) => tile !== false);

  if (tiles.length === 0) return null;
  return (
    <ul className="grid gap-4 md:grid-cols-3">
      {tiles.map((tile) => (
        <li key={tile.href}>
          <CountTile {...tile} />
        </li>
      ))}
    </ul>
  );
}

function WideOverview() {
  const t = useTranslations();
  const { user } = useAppContext();
  const { space, can, routeId } = useSpace();
  const levels = useSectionHeadingLevels();
  const base = `/spaces/${routeId}`;

  const isShared = !space.personal && !space.organization;
  const canAddMember = isShared && can("add", "member");
  const canChat = isShared && space.default_assistant != null && can("read", "default_assistant");

  return (
    <div className="flex w-full min-w-0 flex-col gap-6">
      <PageHeader
        headingLevel={levels.title}
        title={t("overview")}
        isTitleHiddenOnPhone
        actions={
          canAddMember || canChat ? (
            <div className="flex flex-wrap items-center gap-2.5">
              {canAddMember ? <AddMemberDialog variant="header" /> : null}
              {canChat ? (
                <Button
                  label={t("space_new_chat")}
                  variant="secondary"
                  href={`${base}/chat`}
                  icon={<SquarePen aria-hidden="true" />}
                />
              ) : null}
            </div>
          ) : undefined
        }
      />
      <div className="flex flex-col gap-3">
        <Heading level={levels.sub} className="text-3xl font-extrabold break-words">
          {space.personal ? t("hi_user_personal", { firstName: firstNameOf(user) }) : space.name}
        </Heading>
        <p className="text-ax-text-secondary max-w-[70ch]">
          {space.personal
            ? t("personal_space_description")
            : space.description?.trim() || t("welcome_to_space", { space: space.name })}
        </p>
      </div>
      <CountTiles />
    </div>
  );
}
