import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Layout, LayoutContent, LayoutFooter, LayoutHeader } from "@astryxdesign/core/Layout";
import { List, ListItem } from "@astryxdesign/core/List";
import { RadioList, RadioListItem } from "@astryxdesign/core/RadioList";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useTranslations } from "use-intl";
import { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { Collapsible } from "@/components/astryx/collapsible";
import { TextInput } from "@/components/astryx/text-input";
import { QueryStateBoundary, type QueryLike } from "@/components/composites/query-state";
import {
  getFlow,
  insertionKindsQueryOptions,
  toolOptionsQueryOptions,
  updateFlowEditor
} from "./editor-api";
import { problemStatus } from "./editor-fields";
import { describeSaveError, isStaleRevision } from "./field-problems";
import { httpUrlProblem } from "./step-configs";
import {
  kindOption,
  kindRefusalText,
  newStepUpdate,
  uniqueStepName,
  type DocumentFormat,
  type StepKindOption,
  type StepKindPlace
} from "./step-kinds";
import { stepLabel } from "./step-labels";
import {
  STEP_TASKS,
  recommendedTaskIds,
  searchedFormat,
  taskFits,
  taskFlow,
  taskMatches,
  taskStepName,
  type StepTask
} from "./step-tasks";
import type { FlowPublic, ToolOption } from "./step-types";

type Field = "url" | "tool";
type Problems = Partial<Record<Field, string>>;
type Row = { task: StepTask; option: StepKindOption };

function toolKey(tool: Pick<ToolOption, "mcp_server_id" | "tool_id">): string {
  return `${tool.mcp_server_id}:${tool.tool_id}`;
}

function ToolChoice({
  flowId,
  value,
  onChange,
  problem,
  inputRef
}: {
  flowId: string;
  value: string | null;
  onChange: (tool: ToolOption) => void;
  problem?: string;
  inputRef: React.RefObject<HTMLDivElement | null>;
}) {
  const t = useTranslations();
  const options = useQuery(toolOptionsQueryOptions(flowId));
  const items = options.data?.items ?? [];
  const servers = [...new Set(items.map((item) => item.mcp_server_id))];
  return (
    <div ref={inputRef}>
      <Selector
        label={t("flow_step_editor_tool")}
        description={
          options.isError
            ? t("flow_step_editor_tools_failed")
            : options.isSuccess && items.length === 0
              ? t("flow_step_editor_tools_none")
              : t("flow_step_editor_tool_description")
        }
        options={servers.map((serverId) => {
          const serverTools = items.filter((item) => item.mcp_server_id === serverId);
          return {
            type: "section" as const,
            title: serverTools[0]?.mcp_server_name ?? serverId,
            options: serverTools.map((item) => ({
              value: toolKey(item),
              label: item.tool_name,
              description: item.tool_description ?? undefined
            }))
          };
        })}
        value={value ?? undefined}
        placeholder={t("flow_step_editor_tool_placeholder")}
        isLoading={options.isPending}
        hasSearch={items.length > 8}
        isRequired
        onChange={(key) => {
          const item = items.find((candidate) => toolKey(candidate) === key);
          if (item) onChange(item);
        }}
        status={problemStatus(problem)}
        width="100%"
      />
    </div>
  );
}

/** Rows as cards: a calm border, the chosen one tinted, 44 px on touch. */
const ROW =
  "rounded-ax-element border border-ax-border px-3 py-2 hover:bg-ax-hover " +
  "data-[selected=selected]:border-ax-accent data-[selected=selected]:bg-ax-accent-muted";
/** "Tomt steg" is the quiet last row: the same row, dashed. */
const BLANK_ROW = `${ROW} border-dashed`;
const GROUP = "[&_.astryx-radio-list>div]:gap-1.5";

/**
 * The picker inside the dialog. Tasks are offered where the core allows their
 * kind (`kinds`, the core's answer for the place); the others fold into one
 * line that says why. It mounts anew each time the dialog closes, so it opens
 * on the first recommended task; its header stays mounted while the dialog is
 * closed, because the dialog takes its name from the title it finds on open.
 */
function AddStepPicker({
  open,
  flow,
  position,
  kinds,
  pending,
  onCancel,
  onClose,
  onSaved,
  onPendingChange,
  onReloaded
}: {
  open: boolean;
  flow: FlowPublic;
  position: number;
  kinds: QueryLike<StepKindPlace>;
  pending: boolean;
  onCancel: () => void;
  onClose: () => void;
  onSaved: (flow: FlowPublic) => void;
  onPendingChange: (pending: boolean) => void;
  onReloaded: (flow: FlowPublic) => void;
}) {
  const t = useTranslations();
  const text = (key: string) => t(key);
  const announce = useAnnounce();
  const [query, setQuery] = useState("");
  const [chosenId, setChosenId] = useState<string | null>(null);
  const [chosenFormat, setChosenFormat] = useState<DocumentFormat | null>(null);
  const [url, setUrl] = useState("");
  const [tool, setTool] = useState<ToolOption | null>(null);
  const [problems, setProblems] = useState<Problems>({});
  const [formProblem, setFormProblem] = useState<{ message: string; stale: boolean } | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const urlRef = useRef<HTMLInputElement>(null);
  const toolRef = useRef<HTMLDivElement>(null);
  const summaryRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  // Each open starts afresh. The picker stays mounted: a remounted dialog
  // header would take focus from the search for its title again.
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setQuery("");
      setChosenId(null);
      setChosenFormat(null);
      setUrl("");
      setTool(null);
      setProblems({});
      setFormProblem(null);
    }
  }

  const ordered = [...flow.steps].sort((left, right) => left.step_order - right.step_order);
  const before = position > 1 ? (ordered[position - 2] ?? null) : null;
  const rows: Row[] = STEP_TASKS.flatMap((task) => {
    const option = kindOption(kinds.data, task.kind);
    return option && taskFits(task, option) ? [{ task, option }] : [];
  });
  const found = rows.filter((row) => taskMatches(row.task, query, text));
  const allowed = found.filter((row) => row.option.allowed);
  const refused = found.filter((row) => !row.option.allowed);
  const recommendedIds = recommendedTaskIds(before ? before.output_type : null);
  const recommended = allowed.filter((row) => recommendedIds.includes(row.task.id));
  const more = allowed.filter((row) => !recommendedIds.includes(row.task.id));
  const selected =
    allowed.find((row) => row.task.id === chosenId) ?? recommended[0] ?? more[0] ?? null;
  const format = chosenFormat ?? searchedFormat(query);
  const kind = selected?.option.kind;
  const rowName = (task: StepTask) => t(`flow_add_step_${task.id}`);
  const stepName = (task: StepTask) => uniqueStepName(flow, t(taskStepName(task)));

  // What the search leaves and what Enter in it adds, or that nothing can be
  // added here, said once the place's kinds are in (WCAG 4.1.3); clearing the
  // search drops what was said.
  const searched = query.trim();
  const firstMatch = recommended[0] ?? more[0];
  const nothingFound = searched
    ? t("flow_add_step_no_results", { query: searched })
    : t("flow_add_step_none_allowed");
  const searchResult = !kinds.data
    ? null
    : firstMatch
      ? searched
        ? t("flow_add_step_search_result", {
            count: allowed.length,
            name: rowName(firstMatch.task)
          })
        : null
      : nothingFound;
  const announcedSearch = useRef(false);
  useEffect(() => {
    if (searchResult) {
      announce(searchResult);
      announcedSearch.current = true;
    } else if (announcedSearch.current && !searched) {
      announce("");
      announcedSearch.current = false;
    }
  }, [announce, searchResult, searched]);

  const add = useMutation({
    mutationFn: ({ task, option }: Row) =>
      updateFlowEditor(
        flow.id,
        newStepUpdate(flow, position, option, {
          name: stepName(task),
          format,
          url,
          tool: tool
            ? { mcp_server_id: tool.mcp_server_id, tool_id: tool.tool_id, arguments: {} }
            : null,
          prompt: task.prompt ? t(task.prompt) : undefined
        })
      ),
    onMutate: () => onPendingChange(true),
    onSettled: () => onPendingChange(false),
    onSuccess: (updated, { task }) => {
      announce(t("flow_step_editor_added", { name: stepName(task) }));
      onSaved(updated);
      onClose();
    },
    onError: (error, { option }) => {
      if (isStaleRevision(error)) {
        flushSync(() => setFormProblem({ message: t("flow_step_editor_add_stale"), stale: true }));
        summaryRef.current?.focus();
        return;
      }
      const problem = describeSaveError(
        error,
        {
          stepId: "",
          stepOrder: position,
          config: {
            input_source: option.configuration.input_source,
            output_mode: option.configuration.output_mode
          }
        },
        t
      );
      const field: Field | null =
        problem.anchor === "input_config.http" || problem.anchor === "output_config.http"
          ? "url"
          : problem.anchor === "input_config.tool"
            ? "tool"
            : null;
      if (field && problem.otherStepOrder === null) {
        flushSync(() => {
          setProblems({ [field]: problem.message });
          setFormProblem(null);
        });
        focusField(field);
        return;
      }
      const message =
        problem.otherStepOrder !== null
          ? t("flow_step_editor_other_step_problem", {
              step: stepLabel(
                problem.otherStepOrder,
                ordered.find((step) => step.step_order === problem.otherStepOrder)
                  ?.user_description,
                t
              ),
              message: problem.message
            })
          : problem.message;
      flushSync(() => setFormProblem({ message, stale: false }));
      summaryRef.current?.focus();
    }
  });

  const reload = useMutation({
    mutationFn: () => getFlow(flow.id),
    onSuccess: (fresh) => {
      onReloaded(fresh);
      // The banner and its button go: focus waits in the search for the place's kinds.
      flushSync(() => setFormProblem(null));
      searchRef.current?.focus();
      announce(t("flow_step_editor_reloaded"));
    }
  });

  function focusField(field: Field) {
    if (field === "url") urlRef.current?.focus();
    else toolRef.current?.querySelector<HTMLElement>("button, [role=combobox]")?.focus();
  }

  function focusList() {
    const radios = listRef.current?.querySelectorAll<HTMLInputElement>("input[type=radio]");
    const list = [...(radios ?? [])];
    (list.find((radio) => radio.checked) ?? list[0])?.focus();
  }

  /** Adds `row`, or says at its field what it still needs. */
  function confirm(row: Row | null) {
    if (!row || add.isPending) return;
    const found: Problems = {};
    if (row.option.kind === "fetch_http" || row.option.kind === "send_http") {
      const urlProblem = httpUrlProblem(url);
      if (urlProblem === "missing") found.url = t("flow_step_editor_http_url_missing");
      else if (urlProblem === "invalid") found.url = t("flow_step_editor_http_url_invalid");
    }
    if (row.option.kind === "tool" && !tool) found.tool = t("flow_step_editor_tool_required");
    const first = (["url", "tool"] as const).find((field) => found[field]);
    if (first) {
      // The row becomes the choice, so its field is there to say what it needs.
      flushSync(() => {
        setChosenId(row.task.id);
        setProblems(found);
      });
      focusField(first);
      return;
    }
    setProblems({});
    setFormProblem(null);
    add.mutate(row);
  }

  function choose(id: string) {
    setChosenId(id);
    setProblems({});
  }

  /** The row of the radio an event came from, in `members`. */
  function rowOf(members: Row[], target: EventTarget) {
    const id = (target as HTMLElement).closest<HTMLElement>("[data-task]")?.dataset.task;
    return members.find((row) => row.task.id === id) ?? null;
  }

  function group(label: string, members: Row[]) {
    if (members.length === 0) return null;
    return (
      <RadioList
        label={label}
        value={selected?.task.id ?? ""}
        onChange={choose}
        size="sm"
        containerClassName={GROUP}
        // Enter or a double-click adds the row it lands on, chosen or only focused.
        onKeyDown={(event) => {
          if (event.key !== "Enter") return;
          event.preventDefault();
          confirm(rowOf(members, event.target));
        }}
        onDoubleClick={(event) => confirm(rowOf(members, event.target))}
      >
        {members.map(({ task, option }) => {
          const Icon = task.icon;
          const flowLabel = task.id === "blank" ? null : taskFlow(option, format, text);
          const io = flowLabel ? `${flowLabel.from} → ${flowLabel.to}` : null;
          return (
            <RadioListItem
              key={task.id}
              value={task.id}
              data-task={task.id}
              className={task.id === "blank" ? BLANK_ROW : ROW}
              align="first-line"
              startContent={
                <Icon className="text-ax-text-secondary ms-2 size-4 shrink-0" aria-hidden="true" />
              }
              label={rowName(task)}
              description={
                <>
                  {t(`flow_add_step_${task.id}_description`)}
                  {io && (
                    <span className="text-ax-text-secondary wide:hidden block tabular-nums">
                      <span aria-hidden="true">{io}</span>
                    </span>
                  )}
                  {flowLabel && (
                    <span className="sr-only"> {t("flow_add_step_io_spoken", flowLabel)}</span>
                  )}
                </>
              }
              endContent={
                io ? (
                  <Text
                    type="supporting"
                    size="sm"
                    aria-hidden="true"
                    className="phone:hidden whitespace-nowrap tabular-nums"
                  >
                    {io}
                  </Text>
                ) : undefined
              }
            />
          );
        })}
      </RadioList>
    );
  }

  const lands = before
    ? t("flow_add_step_lands_after", {
        step: stepLabel(before.step_order, before.user_description, t)
      })
    : t("flow_add_step_lands_first");

  return (
    <Layout
      header={
        <>
          <DialogHeader
            title={t("flow_step_editor_add_title")}
            subtitle={t("flow_add_step_subtitle")}
            onOpenChange={(open) => {
              if (!open) onCancel();
            }}
          />
          <LayoutHeader>
            <TextInput
              ref={searchRef}
              label={t("flow_add_step_search")}
              isLabelHidden
              placeholder={t("flow_add_step_search")}
              value={query}
              onChange={(value) => {
                setQuery(value);
                setChosenId(null);
              }}
              onKeyDown={(event) => {
                if (event.key === "ArrowDown") {
                  event.preventDefault();
                  focusList();
                }
              }}
              // With a search, Enter adds the first match, which is already chosen.
              onEnter={() => (query.trim() ? confirm(selected) : focusList())}
              startIcon={Search}
              hasClear
              autoComplete="off"
              width="100%"
              hasAutoFocus={open}
            />
          </LayoutHeader>
        </>
      }
      content={
        open ? (
          <LayoutContent>
            <div className="flex flex-col gap-5">
              <div
                ref={summaryRef}
                tabIndex={-1}
                className="focus-visible:outline-ring empty:hidden focus-visible:outline-2 focus-visible:outline-offset-2"
              >
                {formProblem && (
                  <Banner
                    role="alert"
                    status="error"
                    title={t("flow_step_editor_add_refused")}
                    description={formProblem.message}
                    collapsible={false}
                    endContent={
                      formProblem.stale ? (
                        <Button
                          label={t("flow_step_editor_reload")}
                          size="sm"
                          isLoading={reload.isPending}
                          isInterruptible
                          onClick={() => {
                            if (!reload.isPending) reload.mutate();
                          }}
                        />
                      ) : undefined
                    }
                  />
                )}
              </div>
              <QueryStateBoundary
                query={kinds}
                rows={6}
                loadingLabel={t("flow_step_editor_kinds_loading")}
              >
                {() => (
                  <div ref={listRef} className="flex flex-col gap-5">
                    {group(t("flow_add_step_recommended"), recommended)}
                    {group(
                      recommended.length > 0 ? t("flow_add_step_more") : t("flow_add_step_all"),
                      more
                    )}
                    {allowed.length === 0 && (
                      <Text
                        type="supporting"
                        as="p"
                        display="block"
                        className="m-0 py-6 text-center"
                      >
                        {nothingFound}
                      </Text>
                    )}
                    {refused.length > 0 && (
                      <Collapsible
                        // Open when nothing can be added: the reasons are the answer.
                        defaultIsOpen={allowed.length === 0}
                        trigger={
                          <Text type="supporting" size="sm">
                            {t("flow_add_step_refused", { count: refused.length })}
                          </Text>
                        }
                      >
                        <List density="compact">
                          {refused.map(({ task, option }) => (
                            <ListItem
                              key={task.id}
                              startContent={
                                <task.icon
                                  className="text-ax-text-secondary size-4 shrink-0"
                                  aria-hidden="true"
                                />
                              }
                              label={rowName(task)}
                              description={
                                <Text type="supporting" size="sm">
                                  {option.refusals[0]
                                    ? kindRefusalText(option.refusals[0], position, flow, t)
                                    : t("flow_step_editor_kind_block_refused")}
                                </Text>
                              }
                              align="first-line"
                            />
                          ))}
                        </List>
                      </Collapsible>
                    )}
                  </div>
                )}
              </QueryStateBoundary>
            </div>
          </LayoutContent>
        ) : null
      }
      footer={
        open ? (
          <LayoutFooter>
            <form
              noValidate
              className="flex flex-col gap-3"
              onSubmit={(event) => {
                event.preventDefault();
                confirm(selected);
              }}
            >
              {kind === "document" && (
                <RadioList
                  label={t("flow_step_editor_document_format")}
                  value={format}
                  onChange={(value) => setChosenFormat(value === "pdf" ? "pdf" : "docx")}
                  orientation="horizontal"
                  size="sm"
                >
                  <RadioListItem value="docx" label={t("flow_output_type_docx")} />
                  <RadioListItem value="pdf" label={t("flow_output_type_pdf")} />
                </RadioList>
              )}
              {(kind === "fetch_http" || kind === "send_http") && (
                <TextInput
                  ref={urlRef}
                  label={
                    kind === "fetch_http"
                      ? t("flow_step_editor_http_url_get")
                      : t("flow_step_editor_http_url_post")
                  }
                  description={t("flow_step_editor_http_url_description")}
                  value={url}
                  onChange={(value) => {
                    setUrl(value);
                    setProblems((current) => ({ ...current, url: undefined }));
                  }}
                  isRequired
                  autoComplete="off"
                  status={problemStatus(problems.url)}
                  width="100%"
                />
              )}
              {kind === "tool" && (
                <ToolChoice
                  flowId={flow.id}
                  value={tool ? toolKey(tool) : null}
                  onChange={(next) => {
                    setTool(next);
                    setProblems((current) => ({ ...current, tool: undefined }));
                  }}
                  problem={problems.tool}
                  inputRef={toolRef}
                />
              )}
              <div className="flex flex-wrap items-center justify-end gap-x-3 gap-y-2">
                <Text type="supporting" size="sm" className="phone:basis-full me-auto">
                  {lands}
                </Text>
                <Button label={t("cancel")} isDisabled={pending} onClick={onCancel} />
                <Button
                  type="submit"
                  variant="primary"
                  label={
                    selected
                      ? t("flow_add_step_submit", { name: rowName(selected.task) })
                      : t("flow_step_editor_add_title")
                  }
                  isLoading={pending}
                  isInterruptible
                  isDisabled={!selected}
                />
              </div>
            </form>
          </LayoutFooter>
        ) : null
      }
    />
  );
}

/**
 * Adds a step at `position` (1-based): the author picks what the step does,
 * a task or a kind of step, and the step is named after it (renamed in the
 * editor). The kinds the place allows, why the others are refused and the
 * configuration each starts with are the core's answer for the place; the
 * step is saved as one editor change (`new_steps` + `step_order`).
 */
export function AddStepDialog({
  flow: propFlow,
  position: requestedPosition,
  open,
  onOpenChange,
  onSaved
}: {
  flow: FlowPublic;
  position: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: (flow: FlowPublic) => void;
}): React.JSX.Element {
  const [pending, setPending] = useState(false);
  // A draft read again after a stale save, while the dialog stays open.
  const [reloaded, setReloaded] = useState<FlowPublic | null>(null);
  const flow = reloaded && reloaded.draft_revision >= propFlow.draft_revision ? reloaded : propFlow;
  const position = Math.min(Math.max(1, Math.round(requestedPosition)), flow.steps.length + 1);
  const kinds = useQuery({
    ...insertionKindsQueryOptions(flow.id, flow.draft_revision, position),
    enabled: open
  });

  function close() {
    setReloaded(null);
    onOpenChange(false);
  }

  function requestOpenChange(next: boolean) {
    if (!next && pending) return;
    if (next) onOpenChange(true);
    else close();
  }

  return (
    <Dialog
      isOpen={open}
      onOpenChange={requestOpenChange}
      purpose="form"
      width={600}
      maxHeight="85dvh"
    >
      <AddStepPicker
        open={open}
        flow={flow}
        position={position}
        kinds={kinds}
        pending={pending}
        onCancel={() => requestOpenChange(false)}
        onClose={close}
        onSaved={onSaved}
        onPendingChange={setPending}
        onReloaded={setReloaded}
      />
    </Dialog>
  );
}
