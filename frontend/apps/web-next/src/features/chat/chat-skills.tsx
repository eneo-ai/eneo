"use client";

import { BottomSheet } from "@astryxdesign/core/BottomSheet";
import { Button } from "@astryxdesign/core/Button";
import { useMediaQuery } from "@astryxdesign/core/hooks";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Popover } from "@astryxdesign/core/Popover";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { BookOpenCheck, Lock, Plus, RefreshCw, Search, Settings, X } from "lucide-react";
import { useTranslations } from "use-intl";
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type RefObject
} from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { TextInput } from "@astryxdesign/core/TextInput";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError, QueryStateBoundary } from "@/components/composites/query-state";
import {
  FailureText,
  layerReasonText,
  modeLabel,
  usePersonalChatSkills,
  type PersonalSkillMode,
  type PersonalSkillRow
} from "@/features/skills/personal-chat-skills";
import { useSpace } from "@/features/spaces/use-space";
import { SkillDependencies } from "@/features/skills/skill-dependencies";
import { useFocusRescue } from "@/lib/focus-rescue";
import { cn } from "@/lib/utils";
import { COMPOSER_PILL_CLASS, COMPOSER_PILL_COUNT_CLASS } from "./mcp-controls";

type PersonalChatSkills = ReturnType<typeof usePersonalChatSkills>;
/** The library search: as typed, and the query the rows follow after a pause. */
type SearchField = { value: string; onChange: (value: string) => void; query: string };

const SEARCH_DEBOUNCE_MS = 250;

/**
 * What Astryx's Popover adds around its content, above the trigger: the 4 px
 * gap, 12 px of padding above and below and the 16 px gutter at the top of
 * the window.
 */
const POPOVER_CHROME = 44;

/**
 * A chosen "Vid behov" or "Alltid" takes the accent; a chosen "Av" keeps the
 * segment's neutral raised surface, so nothing looks switched on that is
 * off. SegmentedControlItem drops a caller's className, so the rule sits on
 * the group; in forced colours Astryx's own system colours stay.
 */
const ON_MODE_ACCENT =
  "not-forced-colors:[&>[aria-checked=true]:not([data-value=off])]:bg-ax-accent not-forced-colors:[&>[aria-checked=true]:not([data-value=off])]:text-ax-on-accent";

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <p className="text-ax-text-secondary text-xs font-semibold">{title}</p>
      {children}
    </div>
  );
}

function SkillText({ name, description }: { name: string; description: string }) {
  return (
    <div className="min-w-0 flex-1">
      <p className="truncate text-[13px] font-medium">{name}</p>
      {/* One line; the whole description is in the Skills library. */}
      {description && <p className="text-ax-text-secondary truncate text-xs">{description}</p>}
    </div>
  );
}

/** An organisation Skill: read-only, chosen by an administrator. */
function OrganisationRow({ skill }: { skill: PersonalChatSkills["organisation"][number] }) {
  const t = useTranslations();
  return (
    <li className="flex items-start gap-3 py-2">
      <div className="min-w-0 flex-1">
        <SkillText name={skill.display_name} description={skill.description} />
        <SkillDependencies dependencies={skill.dependencies} />
      </div>
      <div className="text-ax-text-secondary flex shrink-0 flex-col items-end gap-0.5 text-xs">
        <span className="flex items-center gap-1">
          <Lock aria-hidden="true" className="size-3.5" />
          {modeLabel(skill.activation_mode, t)}
        </span>
        <span>
          {t(
            skill.execution_blocked
              ? "personal_chat_skills_blocked"
              : "personal_chat_skills_organisation_locked"
          )}
        </span>
      </div>
    </li>
  );
}

/** One of the person's own Skills with its "Av / Vid behov / Alltid" choice. */
function OwnRow({
  row,
  skills,
  stacked
}: {
  row: PersonalSkillRow;
  skills: PersonalChatSkills;
  stacked: boolean;
}) {
  const t = useTranslations();
  const group = useRef<HTMLDivElement>(null);
  const rescue = useFocusRescue();
  const failure = skills.failures[row.skillId] ?? null;
  const latest = skills.canEdit && !row.blocked ? row.latest : null;

  return (
    <li className="flex flex-col gap-2 py-2.5">
      <div className={cn("flex gap-x-4 gap-y-2", stacked ? "flex-col" : "items-center")}>
        <div className="min-w-0 flex-1">
          <SkillText name={row.name} description={row.description} />
          {row.mode !== "off" && <SkillDependencies dependencies={row.dependencies} />}
          {!!row.usedVia?.length && (
            <p className="text-ax-text-secondary mt-1 text-xs">
              {t("skills_reference_used_via", { names: row.usedVia.join(", ") })}
            </p>
          )}
        </div>
        {skills.canEdit ? (
          <SegmentedControl
            ref={group}
            label={t("personal_chat_skills_mode_group_label", { name: row.name })}
            value={row.mode}
            onChange={(mode) =>
              skills.change({
                kind: "mode",
                skillId: row.skillId,
                mode: mode as PersonalSkillMode,
                revisionId: row.revisionId
              })
            }
            isDisabled={row.blocked}
            layout={stacked ? "fill" : "hug"}
            className={cn("shrink-0", ON_MODE_ACCENT, stacked && "[&>[role=radio]]:min-h-11")}
          >
            <SegmentedControlItem value="off" label={modeLabel("off", t)} />
            <SegmentedControlItem value="on_demand" label={modeLabel("on_demand", t)} />
            <SegmentedControlItem value="always" label={modeLabel("always", t)} />
          </SegmentedControl>
        ) : (
          // Without the permission the choice is kept but cannot be changed.
          <span className="text-ax-text-secondary shrink-0 text-xs">{modeLabel(row.mode, t)}</span>
        )}
      </div>
      {row.blocked && (
        <p className="text-ax-text-secondary text-xs">{t("personal_chat_skills_blocked")}</p>
      )}
      {latest && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="text-ax-text-secondary text-xs">
            {t("personal_chat_skills_update_available")}
          </span>
          <Button
            size="sm"
            variant="secondary"
            label={t("personal_chat_skills_use_latest")}
            icon={<RefreshCw aria-hidden="true" />}
            onClick={() => {
              skills.change({ kind: "revision", skillId: row.skillId, revisionId: latest.id });
              // The button goes once the chat uses the latest version.
              rescue(
                () =>
                  group.current?.querySelector<HTMLElement>(
                    '[role="radio"][aria-checked="true"]'
                  ) ?? null
              );
            }}
          />
        </div>
      )}
      {failure && <FailureText message={failure} />}
    </li>
  );
}

/**
 * The person's own Skills: the search, the rows, then the library's state.
 * The Skills in the chat are rows from the start, so they can be changed
 * while the library loads, and when a page of it fails.
 */
function OwnSkills({
  skills,
  stacked,
  search
}: {
  skills: PersonalChatSkills;
  stacked: boolean;
  search: SearchField;
}) {
  const t = useTranslations();
  const { library, rows } = skills;
  const firstPageFailed = library.isError && !library.data;
  const settled = !library.isLoading && !firstPageFailed;

  return (
    <>
      {skills.searchable && (
        <div className="py-1">
          <TextInput
            label={t("personal_chat_skills_search")}
            isLabelHidden
            placeholder={t("personal_chat_skills_search")}
            value={search.value}
            onChange={search.onChange}
            startIcon={Search}
            hasClear
            size="sm"
            width="100%"
          />
        </div>
      )}
      {rows.length > 0 && (
        <ul aria-label={t("personal_chat_skills_own_heading")} className="flex flex-col">
          {rows.map((row) => (
            <OwnRow key={row.skillId} row={row} skills={skills} stacked={stacked} />
          ))}
        </ul>
      )}
      {library.isLoading && <LoadingState rows={2} />}
      {firstPageFailed && (
        <ListError
          error={library.error}
          isRetrying={library.isFetching}
          onRetry={() => void library.refetch()}
        />
      )}
      {/* With more pages to come, nothing found yet is not "none". */}
      {settled && rows.length === 0 && !library.hasNextPage && (
        <p className="text-ax-text-secondary py-2 text-sm">
          {t(search.query ? "personal_chat_skills_search_empty" : "personal_chat_skills_empty")}
        </p>
      )}
      {library.isFetchNextPageError ? (
        <ListError
          error={library.error}
          isRetrying={library.isFetchingNextPage}
          onRetry={() => void library.fetchNextPage()}
        />
      ) : (
        library.hasNextPage && (
          <Button
            label={library.isFetchingNextPage ? t("loading") : t("load_more")}
            variant="ghost"
            size="sm"
            // Loading, it stays enabled so it keeps focus; a second press is ignored.
            isLoading={library.isFetchingNextPage}
            isInterruptible
            onClick={() => {
              if (!library.isFetchingNextPage) void library.fetchNextPage();
            }}
            className="self-start"
          />
        )
      )}
    </>
  );
}

/**
 * A ref for the panel that keeps it within the room above its trigger.
 * Astryx caps a popover to the window, not to that room, so where the
 * composer sits mid-page (the start state) a long list grew over the pill
 * and the composer; the list scrolls inside instead, and the header and
 * links stay in view.
 */
function useFitAbove(anchor?: RefObject<HTMLElement | null>) {
  const panel = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const element = panel.current;
    const trigger = anchor?.current;
    if (!element || !trigger) return;
    const fit = () => {
      const room = trigger.getBoundingClientRect().top - POPOVER_CHROME;
      element.style.maxHeight = `${Math.max(0, room)}px`;
    };
    fit();
    window.addEventListener("resize", fit);
    window.addEventListener("scroll", fit, true);
    return () => {
      window.removeEventListener("resize", fit);
      window.removeEventListener("scroll", fit, true);
    };
  }, [anchor]);
  return panel;
}

/** What the popover and the bottom sheet show: header, both layers, links. */
function SkillsPanel({
  skills,
  stacked,
  search,
  anchor,
  onClose
}: {
  skills: PersonalChatSkills;
  stacked: boolean;
  search: SearchField;
  /** The popover's trigger: the panel fits in the room above it. */
  anchor?: RefObject<HTMLElement | null>;
  /** The sheet's visible close button; the popover has its own. */
  onClose?: () => void;
}) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const { layer, running, canEdit } = skills;
  const base = `/spaces/${routeId}/skills`;
  const panel = useFitAbove(anchor);

  return (
    <div ref={panel} className={cn("flex min-h-0 flex-col gap-3", stacked ? "p-4" : "p-1")}>
      <div className="flex shrink-0 items-start gap-3">
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          <p className="text-sm font-semibold">{t("personal_chat_skills_button")}</p>
          <p className="text-ax-text-secondary text-xs">{t("personal_chat_skills_scope")}</p>
          {running && (
            <p className="text-ax-text-secondary text-xs tabular-nums">
              {t("personal_chat_skills_counts", {
                always: running.always,
                on_demand: running.onDemand
              })}
            </p>
          )}
        </div>
        {onClose && (
          <IconButton
            label={t("close")}
            icon={<X aria-hidden="true" />}
            variant="ghost"
            onClick={onClose}
          />
        )}
      </div>

      <QueryStateBoundary query={skills.configuration} rows={3}>
        {() => (
          <div
            className={cn(
              "flex flex-col gap-4",
              !stacked && "max-h-[28rem] min-h-0 flex-auto overflow-y-auto pe-1"
            )}
          >
            {layer?.status === "suspended" && layer.reason && (
              <Banner
                status="warning"
                title={t("personal_chat_skills_paused_title")}
                description={layerReasonText(layer.reason, layer.detail, t)}
              />
            )}
            {skills.organisation.length > 0 && (
              <Group title={t("personal_chat_skills_organisation_heading")}>
                <ul aria-label={t("personal_chat_skills_organisation_heading")}>
                  {skills.organisation.map((skill) => (
                    <OrganisationRow key={skill.skill_id} skill={skill} />
                  ))}
                </ul>
              </Group>
            )}
            {(canEdit || skills.rows.length > 0) && (
              <Group title={t("personal_chat_skills_own_heading")}>
                <OwnSkills skills={skills} stacked={stacked} search={search} />
              </Group>
            )}
          </div>
        )}
      </QueryStateBoundary>

      {canEdit && (
        <div
          className={cn(
            "border-ax-border flex shrink-0 flex-wrap items-center justify-between gap-2 border-t pt-2",
            stacked && "[&>*]:flex-1"
          )}
        >
          <Button
            href={base}
            label={t("personal_chat_skills_manage")}
            icon={<Settings aria-hidden="true" />}
            variant={stacked ? "secondary" : "ghost"}
            size="sm"
          />
          <Button
            href={`${base}/new`}
            label={t("skills_library_create")}
            icon={<Plus aria-hidden="true" />}
            variant={stacked ? "secondary" : "ghost"}
            size="sm"
          />
        </div>
      )}
    </div>
  );
}

/**
 * The personal chat composer's Skills pill, beside Verktyg: the count of
 * Skills that run, and a popover (a bottom sheet on phones) with the
 * organisation's Skills, read-only, and the person's own with
 * "Av / Vid behov / Alltid". Shown to people who may choose their own
 * Skills, and to anyone whose chat has Skills in it.
 */
export function ChatSkills() {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const pillRef = useRef<HTMLButtonElement>(null);
  // The composer's toolbar goes icon-only below 40rem (max-sm); so does this.
  const wide = useMediaQuery("(min-width: 40rem)");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(searchInput.trim()), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [searchInput]);
  const skills = usePersonalChatSkills({ withLibrary: open, search });
  if (!skills.visible) return null;

  // Refusals and the search belong to the visit that made them: closing forgets them.
  const changeOpen = (next: boolean) => {
    if (!next) {
      skills.dismissFailures();
      setSearchInput("");
      setSearch("");
    }
    setOpen(next);
  };
  const searchField = { value: searchInput, onChange: setSearchInput, query: search };

  const label = skills.running
    ? t("personal_chat_skills_button_label", { count: skills.running.total })
    : t("personal_chat_skills_button");
  const pill = (props: { onClick?: () => void }) => (
    <button
      ref={pillRef}
      type="button"
      aria-haspopup="dialog"
      aria-expanded={open}
      aria-label={label}
      className={COMPOSER_PILL_CLASS}
      {...props}
    >
      <BookOpenCheck aria-hidden="true" className="size-[15px]" />
      <span className="max-sm:sr-only">{t("personal_chat_skills_button")}</span>
      {skills.running && (
        <span aria-hidden="true" className={COMPOSER_PILL_COUNT_CLASS}>
          {skills.running.total}
        </span>
      )}
    </button>
  );

  if (wide) {
    return (
      <Popover
        isOpen={open}
        onOpenChange={changeOpen}
        placement="above"
        alignment="start"
        width={480}
        label={t("personal_chat_skills_button")}
        closeButtonLabel={t("close")}
        // Mounted only while open, so a closed popover holds no radios.
        content={
          open ? (
            <SkillsPanel skills={skills} stacked={false} search={searchField} anchor={pillRef} />
          ) : null
        }
      >
        {pill({})}
      </Popover>
    );
  }
  return (
    <>
      {pill({ onClick: () => setOpen(true) })}
      <BottomSheet
        isOpen={open}
        onOpenChange={changeOpen}
        label={t("personal_chat_skills_button")}
        // A search field brings up the keyboard: only a tall sheet makes room for it.
        height={skills.searchable ? "tall" : "80dvh"}
      >
        <SkillsPanel
          skills={skills}
          stacked
          search={searchField}
          onClose={() => changeOpen(false)}
        />
      </BottomSheet>
    </>
  );
}
