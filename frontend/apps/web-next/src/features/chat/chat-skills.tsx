import { Button } from "@astryxdesign/core/Button";
import { IconButton } from "@astryxdesign/core/IconButton";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { BookOpenCheck, Lock, Plug, Plus, RefreshCw, Search, Settings, X } from "lucide-react";
import { useTranslations } from "use-intl";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { TextInput } from "@/components/astryx/text-input";
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
import {
  COMPOSER_COUNT_CLASS,
  ComposerPanel,
  useFitAbove,
  type ComposerPanelSurface
} from "./composer-panel";
import { ChatTools, ToolsPanel, toolCounts, type ChatToolsProps } from "./mcp-controls";
import { KEYBOARD } from "@/components/astryx/keyboard-hints";

type PersonalChatSkills = ReturnType<typeof usePersonalChatSkills>;
/** The library search: as typed, and the query the rows follow after a pause. */
type SearchField = { value: string; onChange: (value: string) => void; query: string };

const SEARCH_DEBOUNCE_MS = 250;

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
            {...KEYBOARD.search}
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

/** What the popover and the bottom sheet show: header, both layers, links. */
function SkillsPanel({
  skills,
  stacked,
  search,
  anchor,
  onClose,
  tabbed = false
}: {
  skills: PersonalChatSkills;
  stacked: boolean;
  search: SearchField;
  /** The popover's trigger: the panel fits in the room above it. */
  anchor?: HTMLElement | null;
  /** The sheet's visible close button; the popover has its own. */
  onClose?: () => void;
  /** Under a tab that already names the panel: no title, padding or close button here. */
  tabbed?: boolean;
}) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const { layer, running, canEdit } = skills;
  const base = `/spaces/${routeId}/skills`;
  const panel = useFitAbove(anchor);

  return (
    <div
      ref={panel}
      className={cn("flex min-h-0 flex-col gap-3", tabbed ? "flex-auto" : stacked ? "p-4" : "p-1")}
    >
      <div className="flex shrink-0 items-start gap-3">
        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
          {!tabbed && <p className="text-sm font-semibold">{t("personal_chat_skills_button")}</p>}
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

type PanelTab = "tools" | "skills";

/**
 * Verktyg and Skills as two tabs of one panel: the tabs name the panels, so
 * neither panel repeats its title, and the sheet's close button sits beside
 * them. Only the tab in view is mounted.
 */
function ToolsAndSkills({
  tools,
  skills,
  search,
  tab,
  onTabChange,
  surface
}: {
  tools: ChatToolsProps;
  skills: PersonalChatSkills;
  search: SearchField;
  tab: PanelTab;
  onTabChange: (tab: PanelTab) => void;
  surface: ComposerPanelSurface;
}) {
  const t = useTranslations();
  const { stacked, anchor, onClose } = surface;
  const panel = useFitAbove(anchor);
  const toolsPanelId = useId();
  const skillsPanelId = useId();
  const panelClass = "flex min-h-0 flex-auto flex-col";

  return (
    <div ref={panel} className={cn("flex min-h-0 flex-col gap-3", stacked ? "p-4" : "p-1")}>
      <div className="flex shrink-0 items-center justify-between gap-3">
        <TabList
          value={tab}
          onChange={(value) => onTabChange(value === "skills" ? "skills" : "tools")}
          role="tablist"
          size="sm"
          aria-label={t("chat_tools")}
        >
          <Tab
            value="tools"
            label={t("chat_tools")}
            panelId={toolsPanelId}
            endContent={<span className={COMPOSER_COUNT_CLASS}>{toolCounts(tools).active}</span>}
          />
          <Tab
            value="skills"
            label={t("personal_chat_skills_button")}
            panelId={skillsPanelId}
            endContent={
              skills.running && <span className={COMPOSER_COUNT_CLASS}>{skills.running.total}</span>
            }
          />
        </TabList>
        {onClose && (
          <IconButton
            label={t("close")}
            icon={<X aria-hidden="true" />}
            variant="ghost"
            onClick={onClose}
          />
        )}
      </div>
      <div
        id={toolsPanelId}
        role="tabpanel"
        aria-label={t("chat_tools")}
        hidden={tab !== "tools"}
        className={panelClass}
      >
        {tab === "tools" && <ToolsPanel {...tools} stacked={stacked} tabbed />}
      </div>
      <div
        id={skillsPanelId}
        role="tabpanel"
        aria-label={t("personal_chat_skills_button")}
        hidden={tab !== "skills"}
        className={panelClass}
      >
        {tab === "skills" && (
          <SkillsPanel skills={skills} stacked={stacked} search={search} tabbed />
        )}
      </div>
    </div>
  );
}

/**
 * The personal chat composer's pill for Verktyg and Skills: one control, so
 * the footer holds on a phone. It carries the count of tools that are on and
 * Skills that run, and opens a popover (a bottom sheet on phones) with a tab
 * for each: the tools' switches, and the organisation's Skills, read-only,
 * with the person's own on "Av / Vid behov / Alltid". A chat with only one of
 * the two shows that one under its own name; Skills are shown to people who
 * may choose their own, and to anyone whose chat has Skills in it.
 */
export function ChatSkills({ tools }: { tools?: ChatToolsProps } = {}) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<PanelTab>("tools");
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(searchInput.trim()), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [searchInput]);
  const skills = usePersonalChatSkills({ withLibrary: open, search });
  const toolCount = tools ? toolCounts(tools) : null;
  const withTools = tools && toolCount && toolCount.total > 0 ? { tools, count: toolCount } : null;
  if (!skills.visible) return withTools ? <ChatTools {...withTools.tools} /> : null;

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
  const skillsName = skills.running
    ? t("chat_skills_named", { count: skills.running.total })
    : t("personal_chat_skills_button");
  // A search field brings up the keyboard: only a tall sheet makes room for it.
  const sheetHeight = skills.searchable ? "tall" : "80dvh";

  if (!withTools) {
    return (
      <ComposerPanel
        icon={BookOpenCheck}
        text={t("personal_chat_skills_button")}
        name={skillsName}
        count={skills.running?.total}
        label={t("personal_chat_skills_button")}
        open={open}
        onOpenChange={changeOpen}
        width={480}
        sheetHeight={sheetHeight}
      >
        {({ stacked, anchor, onClose }) => (
          <SkillsPanel
            skills={skills}
            stacked={stacked}
            search={searchField}
            anchor={anchor}
            onClose={onClose}
          />
        )}
      </ComposerPanel>
    );
  }

  const running = skills.running?.total ?? 0;
  const active = withTools.count.active + running;
  return (
    <ComposerPanel
      icon={Plug}
      text={t("chat_tools")}
      // The pill shows the two counts as one; its name says which is which.
      name={t("chat_tools_and_skills_named", {
        count: active,
        tools: withTools.count.active,
        skills: running
      })}
      count={active}
      label={t("chat_tools")}
      open={open}
      onOpenChange={changeOpen}
      width={480}
      sheetHeight={sheetHeight}
    >
      {(surface) => (
        <ToolsAndSkills
          tools={withTools.tools}
          skills={skills}
          search={searchField}
          tab={tab}
          onTabChange={setTab}
          surface={surface}
        />
      )}
    </ComposerPanel>
  );
}
