import { Button } from "@astryxdesign/core/Button";
import { useCollator } from "@astryxdesign/core/i18n";
import {
  pixel,
  proportional,
  useTableSortable,
  useTableSortableState,
  type TableColumn,
  type TableSortComparator,
  type TableSortState
} from "@astryxdesign/core/Table";
import { VisuallyHidden } from "@astryxdesign/core/VisuallyHidden";
import { useMediaQuery } from "@astryxdesign/core/hooks";
import { useQuery } from "@tanstack/react-query";
import { Plus, SearchX, Upload, Workflow } from "lucide-react";
import { useTranslations } from "use-intl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Table } from "@/components/astryx/table";
import { ClientTime } from "@/components/composites/client-time";
import { EmptyState } from "@/components/composites/empty-state";
import { PageHeader } from "@/components/composites/page-header";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { ResourceGroup } from "@/components/composites/resource-group";
import { ResourceCollection } from "@/components/composites/resource-tile";
import { StatusLabel } from "@/components/composites/status-label";
import { useAppContext } from "@/components/providers/app-context";
import { DockedActions } from "@/components/shell/docked-actions";
import { browserApi } from "@/lib/api/browser";
import { useElementWidth } from "@/lib/hooks/use-element-width";
import { HANDHELD_QUERY, MOBILE_QUERY, usePhoneScreen } from "@/lib/hooks/use-media-match";
import { useSearchDraft } from "@/lib/hooks/use-search-draft";
import Link from "@/lib/link";
import { replaceUrl, usePathname, useSearchParams } from "@/lib/navigation";
import { useSectionHeadingLevels } from "@/features/spaces/frame/space-frame";
import { RemovalFocusScope } from "@/features/spaces/removal";
import { ResourceFilterInput, useFilterShown } from "@/features/spaces/resource-filter-input";
import { ResourceViewControls, useResourceView } from "@/features/spaces/resource-view";
import { useSpace } from "@/features/spaces/use-space";
import { FlowActionScope, FlowActions } from "./actions";
import { flowsListQueryOptions, type FlowSparse } from "./flows-api";
import { flowKindLine } from "./flow-labels";
import { flowChangedAt, flowOwner, matchingFlows } from "./flow-list-filter";
import { FlowPackageImportDialog } from "./flow-package-import-dialog";
import { flowListHref, parseFlowListSearch } from "./flow-search";
import { NewFlowDialog } from "./new-flow-dialog";
import { FlowTile } from "./tile";

type SortKey = "updated" | "name" | "status";

const DEFAULT_SORT: TableSortState<SortKey> = [{ sortKey: "updated", direction: "descending" }];

/**
 * The room the table needs for every column: the fixed ones (status, steps, owner, changed and
 * the menu, 654 px) and a name column wide enough for a name and its description (about 270 px).
 */
const FULL_TABLE_MIN_WIDTH = 924;

/**
 * A space's flows, as cards or a table, the last changed first: name and
 * description, what each takes in and gives back, whether it is published,
 * how many steps it has, whose it is and when it last changed. Those who
 * manage flows see them in two groups, published and drafts; others see the
 * published ones only. The search lives in the address. "Nytt flöde" creates
 * an empty draft and opens it; a flow is built on its own page, by hand or in
 * its chat. A flow's menu follows what the core says the caller may do with it.
 */
export function FlowsPage() {
  const levels = useSectionHeadingLevels();
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const { can, user } = useAppContext();
  const collator = useCollator();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);
  const flows = useQuery(flowsListQueryOptions(browserApi, space.id));
  // Others see published flows only, so only those who manage flows see the state, by which
  // the flows are grouped and can be sorted.
  const canManage = can("flows_manage");
  // On a phone the title is for screen readers only (the space's active tab names the page), so
  // focus that a removal or an action needs to put somewhere goes to the visible page instead.
  const phone = usePhoneScreen();
  const focusTarget = phone ? panelRef : headingRef;
  // A phone in a hand runs and reviews flows; building one (many settings, prompts and
  // steps) is for a computer, so nothing here offers to.
  const handheld = useMediaQuery(HANDHELD_QUERY);
  // Without room for every column (below `lg`, or beside an open sidebar) the steps and the
  // owner go under the name.
  const narrowScreen = useMediaQuery(MOBILE_QUERY);
  const compact =
    useElementWidth(panelRef, (width) => width < FULL_TABLE_MIN_WIDTH) ?? narrowScreen;

  const pathname = usePathname();
  const searchParams = useSearchParams();
  const addressQuery = parseFlowListSearch({ q: searchParams.get("q") }).q ?? "";
  // The list follows each key; the address follows once typing pauses.
  const { draft, setDraft, settled } = useSearchDraft(addressQuery);
  useEffect(() => {
    if (settled !== addressQuery) {
      replaceUrl(flowListHref(pathname, searchParams, { q: settled }));
    }
  }, [settled, addressQuery, pathname, searchParams]);

  const items = useMemo(() => flows.data ?? [], [flows.data]);
  const filterShown = useFilterShown(items.length);
  const query = filterShown ? draft : "";
  const matched = useMemo(
    () => matchingFlows(items, query, (flow) => flowKindLine(flow, t)),
    [items, query, t]
  );
  const { view, chooseView } = useResourceView("flows", "cards");
  const [sort, setSort] = useState(DEFAULT_SORT);
  const comparePublished = useCallback(
    (a: boolean, b: boolean) =>
      collator.compare(t(a ? "published" : "draft"), t(b ? "published" : "draft")),
    [collator, t]
  );
  const comparators = useMemo<Record<SortKey, TableSortComparator<FlowSparse>>>(
    () => ({
      updated: (a, b) => flowChangedAt(a) - flowChangedAt(b),
      name: (a, b) => collator.compare(a.name, b.name),
      status: (a, b) => comparePublished(a.published_version != null, b.published_version != null)
    }),
    [collator, comparePublished]
  );
  const { sortedData: shown, sortConfig } = useTableSortableState<FlowSparse, SortKey>({
    data: matched,
    comparators,
    // As the filter: a list too short for the control keeps no order it cannot change.
    sort: filterShown ? sort : DEFAULT_SORT,
    onSortChange: setSort,
    allowUnsortedState: false
  });
  const sortPlugin = useTableSortable<FlowSparse, SortKey>(sortConfig);
  const hasActions = !handheld && items.some((flow) => flow.permissions.can_delete);

  /** Whose the flow is, in words; `you` is what the viewer's own flows say. */
  function ownerLabel(
    flow: FlowSparse,
    you: string | null = t("flow_list_owner_you")
  ): string | null {
    const owner = flowOwner(flow, user.id, space.members.items);
    if (!owner) return null;
    if (owner.kind === "member") return owner.name;
    return owner.kind === "you" ? you : t("flow_list_owner_unknown");
  }

  const createActions =
    canManage && !handheld ? (
      <>
        <Button
          label={t("flow_editor_tools_package_import")}
          icon={<Upload aria-hidden="true" />}
          onClick={() => setImporting(true)}
        />
        <Button
          label={t("flows_new")}
          variant="primary"
          icon={<Plus aria-hidden="true" />}
          onClick={() => setCreating(true)}
        />
      </>
    ) : null;

  const columns: TableColumn<FlowSparse>[] = [
    {
      key: "name",
      header: t("name"),
      width: proportional(3),
      sortable: true,
      renderCell: (flow) => {
        const kind = flowKindLine(flow, t);
        // As on the cards, the line names the owner only when it is someone else.
        const owner = ownerLabel(flow, null);
        const steps = t("flows_step_count", { count: flow.step_count });
        return (
          <span className="flex min-w-0 flex-col gap-0.5 py-1">
            <Link
              href={`/spaces/${routeId}/flows/${flow.id}`}
              className="text-ax-text focus-visible:outline-ring rounded-ax-inner inline-flex min-h-6 w-fit items-center font-semibold break-words hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11"
            >
              {flow.name}
            </Link>
            {flow.description ? (
              <span className="text-ax-text-secondary text-xs break-words">{flow.description}</span>
            ) : null}
            {kind ? <span className="text-ax-text-secondary text-xs">{kind}</span> : null}
            {compact ? (
              <span className="text-ax-text-secondary text-xs">
                {owner ? `${steps} · ${t("flows_row_owner", { name: owner })}` : steps}
              </span>
            ) : null}
          </span>
        );
      }
    },
    ...(canManage
      ? [
          {
            key: "status",
            header: t("status"),
            width: pixel(190),
            sortable: true,
            renderCell: (flow: FlowSparse) => (
              <StatusLabel
                status={flow.published_version != null ? "success" : "neutral"}
                label={
                  flow.published_version != null
                    ? t("flows_status_published", { version: flow.published_version })
                    : t("flows_status_draft")
                }
              />
            )
          }
        ]
      : []),
    ...(compact
      ? []
      : [
          {
            key: "steps",
            header: t("flows_steps_heading"),
            width: pixel(110),
            renderCell: (flow: FlowSparse) => t("flows_step_count", { count: flow.step_count })
          },
          {
            key: "owner",
            header: t("flow_list_owner"),
            width: pixel(120),
            renderCell: (flow: FlowSparse) => (
              <span className="break-words">{ownerLabel(flow) ?? "—"}</span>
            )
          }
        ]),
    {
      key: "updated",
      header: t("flows_updated"),
      width: pixel(170),
      sortable: true,
      // The date the list sorts by: a flow never changed since it was created shows when that was.
      renderCell: (flow) => {
        const changed = flow.updated_at ?? flow.created_at;
        return changed ? <ClientTime value={changed} format="auto" /> : "—";
      }
    },
    ...(hasActions
      ? [
          {
            key: "actions",
            header: <VisuallyHidden>{t("actions")}</VisuallyHidden>,
            width: pixel(64),
            renderCell: (flow: FlowSparse) => <FlowActions flow={flow} />
          }
        ]
      : [])
  ];

  const collection = (members: FlowSparse[], title: string) => (
    <ResourceCollection
      desktopList={
        view === "list" ? (
          <Table
            data={members}
            columns={columns}
            idKey="id"
            aria-label={title}
            pinnedColumn="name"
            plugins={{ sort: sortPlugin }}
            className="[--table-sticky-background:var(--color-ax-surface)]"
          />
        ) : undefined
      }
    >
      {members.map((flow) => (
        // A card names the owner only when it is someone else's.
        <FlowTile key={flow.id} flow={flow} owner={ownerLabel(flow, null)} />
      ))}
    </ResourceCollection>
  );
  const groups = [true, false].map((published) => ({
    published,
    title: t(published ? "published" : "drafts"),
    members: shown.filter((flow) => (flow.published_version != null) === published)
  }));
  if (sortConfig.sort[0]?.sortKey === "status") {
    const direction = sortConfig.sort[0].direction === "ascending" ? 1 : -1;
    groups.sort((a, b) => comparePublished(a.published, b.published) * direction);
  }

  return (
    <RemovalFocusScope target={focusTarget}>
      <FlowActionScope focusTarget={focusTarget}>
        <div
          ref={panelRef}
          tabIndex={-1}
          className="focus-visible:outline-ring rounded-ax-element flex w-full flex-col gap-6 focus-visible:outline-2 focus-visible:outline-offset-4"
        >
          <PageHeader
            headingLevel={levels.title}
            headingRef={headingRef}
            title={t("flows")}
            description={t("flows_list_description")}
            isTitleHiddenOnPhone
            actions={
              createActions ? (
                <DockedActions label={t("space_flows_actions")}>{createActions}</DockedActions>
              ) : undefined
            }
          />
          <QueryStateBoundary query={flows} rows={3}>
            {() =>
              items.length === 0 ? (
                <EmptyState
                  icon={<Workflow />}
                  hue="purple"
                  headingLevel={levels.sub}
                  title={t("flows_empty_title")}
                  description={t("flows_empty_description")}
                  actions={
                    createActions ? (
                      <div className="flex flex-wrap items-center gap-2">{createActions}</div>
                    ) : undefined
                  }
                />
              ) : (
                <>
                  {filterShown ? (
                    <div className="phone:flex-nowrap flex flex-wrap items-center justify-between gap-3">
                      <ResourceFilterInput
                        className="phone:flex-1"
                        value={draft}
                        onChange={setDraft}
                        label={t("flow_list_search_aria")}
                        placeholder={t("flow_list_search_placeholder")}
                        resultCount={shown.length}
                        inputRef={searchRef}
                      />
                      <ResourceViewControls
                        view={view}
                        onViewChange={chooseView}
                        sortConfig={sortConfig}
                        options={[
                          { key: "updated", label: t("flows_updated") },
                          { key: "name", label: t("name") },
                          ...(canManage ? [{ key: "status" as const, label: t("status") }] : [])
                        ]}
                      />
                    </div>
                  ) : null}
                  {shown.length === 0 ? (
                    <EmptyState
                      isAnnounced={false}
                      icon={<SearchX />}
                      headingLevel={levels.sub}
                      isCompact
                      title={t("flow_list_no_match_title")}
                      actions={
                        <Button
                          label={t("flow_list_clear_search")}
                          onClick={() => {
                            setDraft("");
                            searchRef.current?.focus();
                          }}
                        />
                      }
                    />
                  ) : canManage ? (
                    <div className="flex flex-col gap-6">
                      {groups.map((group) => (
                        <ResourceGroup
                          key={String(group.published)}
                          title={group.title}
                          headingLevel={levels.sub}
                          hidden={group.members.length === 0}
                        >
                          {collection(group.members, `${t("flows")} · ${group.title}`)}
                        </ResourceGroup>
                      ))}
                    </div>
                  ) : (
                    collection(shown, t("flows"))
                  )}
                </>
              )
            }
          </QueryStateBoundary>
          {handheld && canManage ? (
            <p className="text-ax-text-secondary -mt-2 text-sm">{t("flows_create_on_desktop")}</p>
          ) : null}
        </div>
        <NewFlowDialog open={creating} onOpenChange={setCreating} />
        {canManage ? (
          <FlowPackageImportDialog open={importing} onOpenChange={setImporting} />
        ) : null}
      </FlowActionScope>
    </RemovalFocusScope>
  );
}
