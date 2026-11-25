import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { Link } from "@astryxdesign/core/Link";
import {
  MetadataList,
  MetadataListItem,
  type MetadataListProps
} from "@astryxdesign/core/MetadataList";
import { Heading } from "@astryxdesign/core/Text";
import { type QueryKey, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Clock } from "lucide-react";
import { type ReactNode, useEffect, useEffectEvent, useId, useRef, useState } from "react";
import { useFormatter, useTranslations } from "use-intl";
import { TextInput } from "@/components/astryx/text-input";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError } from "@/components/composites/query-state";
import { useAppContext } from "@/components/providers/app-context";
import { parseRetentionDays, RETENTION_MAX_DAYS } from "@/features/spaces/retention-days";
import { useSpace } from "@/features/spaces/use-space";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { toastApiError } from "@/lib/api/toast";
import { usePhoneScreen } from "@/lib/hooks/use-media-match";
import { toast } from "@/lib/toast";
import { flowKeys, type FlowPublic } from "./flows-api";

const policyKey = (flowId: string) => ["flows", "retention", flowId] as const;
type PolicySettings = Schema<"FlowRunRetentionPolicySettings">;

/** The space's cap from a 9086 refusal, or null for any other error. */
function refusedCap(error: unknown): number | null {
  if (!(error instanceof EneoApiError) || error.code !== 9086) return null;
  const { cap_days: days, cap_origin: origin } = error.context ?? {};
  return origin === "space" && typeof days === "number" ? days : null;
}

/** Keeps a name or a date on one line: its spaces become no-break spaces. */
const unbroken = (text: string) => text.replaceAll(" ", "\u00a0");

/** Today's date `days` calendar days back. */
function daysAgo(days: number) {
  const date = new Date();
  date.setDate(date.getDate() - days);
  return date;
}

/**
 * After how many days a finished run is removed automatically, or null when none is.
 * Only a space time removes runs, never in a personal space, and the space's time caps
 * the flow's. The one rule for the section's status line, the phone's folded line and
 * the dialog's warning.
 */
export function automaticRemovalDays({
  personalSpace,
  spaceDays,
  flowDays
}: {
  personalSpace: boolean;
  spaceDays: number | null;
  flowDays: number | null;
}): number | null {
  return personalSpace || spaceDays === null ? null : Math.min(flowDays ?? spaceDays, spaceDays);
}

/** The same, read from what the flow says applies to its run history. */
function removalDaysOf(flow: FlowPublic, personalSpace: boolean) {
  const { contributors } = flow.run_history_retention;
  return automaticRemovalDays({
    personalSpace,
    spaceDays: contributors.space?.days ?? null,
    flowDays: contributors.flow?.days ?? null
  });
}

/**
 * Who may change the flow's retention here, and where the space's time is set for the
 * one who may set it. A flow time takes the right to set retention in the space (its
 * admin, or a personal space's owner who may edit the flow) and the permission to
 * manage retention: the backend refuses everyone else. The link takes the right to edit
 * the space and that permission, as the space's own field does, and the organization's
 * space has no field to link to.
 */
export function useFlowRetentionAccess(mayEditFlow: boolean) {
  const { routeId, space, can: spaceCan } = useSpace();
  const managesRetention = useAppContext().can("retention_manage");
  const editsSpace = spaceCan("edit", "space");
  return {
    mayChange: (space.personal ? mayEditFlow : editsSpace) && managesRetention,
    spaceSettingsHref:
      editsSpace && managesRetention && !space.personal && !space.organization
        ? `/spaces/${routeId}/settings?section=security#security`
        : undefined
  };
}

/** A link to the space's retention time, a full touch target on a coarse pointer. */
function SpaceLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} className="inline-flex items-center self-start pointer-coarse:min-h-11">
      {children}
    </Link>
  );
}

/**
 * The flow's retention as a section of its settings: first in words whether runs are
 * removed (a status line whose icon tells the two apart by shape), then why or who
 * changes it, then where the time comes from, which runs it covers and what goes and
 * what stays. The change (`action`) sits in the heading's row, on a phone under the
 * status line. Without it, the person is told who changes retention.
 */
export function FlowRetentionSection({
  flow,
  personalSpace,
  label,
  headingLevel = 3,
  action,
  spaceSettingsHref
}: {
  flow: FlowPublic;
  personalSpace: boolean;
  /** The flow read views' label column. */
  label: MetadataListProps["label"];
  headingLevel?: 2 | 3;
  action?: ReactNode;
  spaceSettingsHref?: string;
}) {
  const t = useTranslations();
  const phone = usePhoneScreen();
  const headingId = useId();
  const { contributors } = flow.run_history_retention;
  const spaceDays = contributors.space?.days ?? null;
  const flowDays = contributors.flow?.days ?? null;
  const removes = removalDaysOf(flow, personalSpace);
  // A personal space's time is never the flow's cap, so it has no row and no link.
  const href = personalSpace ? undefined : spaceSettingsHref;
  const explanation = personalSpace
    ? t("flows_retention_personal")
    : spaceDays !== null
      ? null
      : flowDays === null
        ? t("flows_retention_applies_none")
        : t("flows_retention_waits_for_space", { days: flowDays });
  const permission = unbroken(t("permission_retention_manage"));
  const who = action
    ? null
    : t(personalSpace ? "flows_retention_who_changes_personal" : "flows_retention_who_changes", {
        permission
      });
  const StatusIcon = removes === null ? Ban : Clock;

  return (
    <section
      aria-labelledby={headingId}
      className="border-ax-border flex min-w-0 flex-col gap-3 border-t pt-5"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Heading level={headingLevel} id={headingId} weight="semibold" className="text-base">
          {t("flows_retention_section_heading")}
        </Heading>
        {phone ? null : action}
      </div>
      <div className="mt-1 flex flex-col gap-1">
        <p className="text-ax-text m-0 flex items-start gap-2 font-medium">
          <StatusIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          {removes === null
            ? t("flows_retention_status_off")
            : t("flows_retention_status_on", { days: removes })}
        </p>
        {explanation ? (
          <p className="text-ax-text-secondary m-0 ps-6 text-sm">{explanation}</p>
        ) : null}
        {who ? <p className="text-ax-text-secondary m-0 ps-6 text-sm">{who}</p> : null}
        {href && spaceDays === null ? (
          <span className="flex ps-6 text-sm">
            <SpaceLink href={href}>{t("flows_retention_space_link_set")}</SpaceLink>
          </span>
        ) : null}
      </div>
      {phone && action ? action : null}
      <MetadataList label={label}>
        <MetadataListItem label={t("flows_retention_row_flow")}>
          {flowDays === null
            ? t(
                personalSpace || spaceDays === null
                  ? "flows_retention_none"
                  : "flows_retention_flow_none"
              )
            : !personalSpace && spaceDays !== null && flowDays > spaceDays
              ? t("flows_retention_longer_saved", { days: flowDays })
              : t("flows_retention_days", { days: flowDays })}
        </MetadataListItem>
        {personalSpace ? null : (
          <MetadataListItem label={t("flows_retention_row_space")}>
            {spaceDays === null ? (
              t("flows_retention_none")
            ) : (
              <span className="flex flex-wrap items-baseline gap-x-3">
                {t("flows_retention_space_cap_value", { days: spaceDays })}
                {href ? <SpaceLink href={href}>{t("flows_retention_space_link")}</SpaceLink> : null}
              </span>
            )}
          </MetadataListItem>
        )}
        {removes === null ? null : (
          <>
            <MetadataListItem label={t("flows_retention_row_scope")}>
              {t("flows_retention_scope_value")}
            </MetadataListItem>
            <MetadataListItem label={t("flows_retention_row_removed")}>
              {t("flows_retention_removed_value")}
            </MetadataListItem>
            <MetadataListItem label={t("flows_retention_row_kept")}>
              {t("flows_retention_kept_value")}
            </MetadataListItem>
          </>
        )}
      </MetadataList>
    </section>
  );
}

/**
 * The retention in a line, for a phone whose settings are folded: whether runs are
 * removed, by the same rule as the section's status line.
 */
export function FlowRetentionFoldedLine({
  flow,
  personalSpace,
  className
}: {
  flow: FlowPublic;
  personalSpace: boolean;
  className?: string;
}) {
  const t = useTranslations();
  const removes = removalDaysOf(flow, personalSpace);
  return (
    <p className={className}>
      {removes === null
        ? t("flows_retention_collapsed_off")
        : t("flows_retention_collapsed_on", { days: removes })}
    </p>
  );
}

/**
 * The flow's own time, or none to use the space's. It has an endpoint of its own and
 * stays open on a published flow: it changes when runs may be purged, not the
 * definition, so it is no part of the settings form. Saving deletes nothing itself, but
 * a shorter time lets the space's automatic removal take older runs at a coming check,
 * so the dialog warns, with the date the new time reaches back to, as soon as a shorter
 * time is typed, and its save button then says it removes. In a personal space nothing
 * is removed automatically, so it never warns.
 */
export function FlowRetentionDialog({
  flow,
  open,
  onOpenChange,
  personalSpace = false,
  spaceSettingsHref
}: {
  flow: FlowPublic;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Runs in a personal space are not removed automatically; the time serves the purge. */
  personalSpace?: boolean;
  /** The space's settings, for the one who may set the space's time. */
  spaceSettingsHref?: string;
}) {
  const t = useTranslations();
  // The space's time does not remove runs in a personal space: the field's text says so.
  const subtitle = personalSpace ? undefined : t("flows_retention_dialog_subtitle");
  const phone = usePhoneScreen();
  const policy = useQuery({
    queryKey: policyKey(flow.id),
    enabled: open,
    queryFn: ({ signal }) =>
      unwrap(
        browserApi.GET("/api/v1/settings/flow-run-retention-policy/flows/{flow_id}", {
          params: { path: { flow_id: flow.id } },
          signal
        })
      )
  });
  return (
    <Dialog
      isOpen={open}
      onOpenChange={onOpenChange}
      purpose="form"
      width={480}
      variant={phone ? "fullscreen" : "standard"}
      // Astryx finds the title when the dialog mounts, and a closed one renders nothing.
      aria-label={t("flows_retention_change")}
    >
      {!open ? null : policy.data ? (
        <RetentionForm
          flow={flow}
          settings={policy.data}
          personalSpace={personalSpace}
          spaceSettingsHref={personalSpace ? undefined : spaceSettingsHref}
          subtitle={subtitle}
          onClose={() => onOpenChange(false)}
        />
      ) : (
        <Layout
          header={
            <DialogHeader
              title={t("flows_retention_change")}
              subtitle={subtitle}
              onOpenChange={onOpenChange}
            />
          }
          content={
            <LayoutContent>
              {policy.isError ? (
                <ListError
                  error={policy.error}
                  title={t("flows_retention_load_failed")}
                  onRetry={() => void policy.refetch()}
                  isRetrying={policy.isFetching}
                />
              ) : (
                <LoadingState rows={2} label={t("flows_retention_change")} />
              )}
            </LayoutContent>
          }
        />
      )}
    </Dialog>
  );
}

function RetentionForm({
  flow,
  settings,
  personalSpace,
  spaceSettingsHref,
  subtitle,
  onClose
}: {
  flow: FlowPublic;
  settings: PolicySettings;
  personalSpace: boolean;
  spaceSettingsHref?: string;
  subtitle?: string;
  onClose: () => void;
}) {
  const t = useTranslations();
  const format = useFormatter();
  const announce = useAnnounce();
  const formId = useId();
  const warningId = useId();
  const queryClient = useQueryClient();
  const savedDays = settings.local_policy?.days ?? null;
  // Until the person edits it, the field shows the Flow's time as last read, so a
  // read that brings another admin's change replaces it. A clear is an edit too.
  const [draft, setDraft] = useState<{ text: string } | null>(null);
  const text = draft ? draft.text : (savedDays?.toString() ?? "");
  // Read at every key, as the space's field is, so the warning and the button's words
  // change while the person types and nothing moves under a click. Undefined is invalid.
  const days = draft ? parseRetentionDays(draft.text.trim()) : savedDays;
  const [refused, setRefused] = useState(false);
  // The space's time as the server last gave it, by a read or by a refusal.
  const spaceDays = settings.inherited_policy?.days ?? null;
  // The field's value is over the space's time; a new value clears it.
  const [overCap, setOverCap] = useState(false);
  // The shorter time whose first Enter was held, so its warning is read before it saves.
  const [enterHeldFor, setEnterHeldFor] = useState<number | null>(null);
  const field = useRef<HTMLInputElement>(null);

  /** Writes what the server just said; an older read still in flight must not replace it. */
  const writeAnswer = async <T,>(key: QueryKey, update: (current?: T) => T | undefined) => {
    await queryClient.cancelQueries({ queryKey: key, exact: true });
    queryClient.setQueryData<T>(key, update);
  };

  const save = useMutation({
    // `expected` and `expectedSpace` are the time that applied and the space's time when the
    // warning was decided; the server refuses the save (409 `retention_time_changed`) when
    // another administrator has changed either since. The space's time counts on its own:
    // giving the space a time starts the removal without changing the time that applies.
    mutationFn: ({
      sent,
      expected,
      expectedSpace
    }: {
      sent: number | null;
      expected: number | null;
      expectedSpace: number | null;
    }) =>
      unwrap(
        browserApi.PUT("/api/v1/settings/flow-run-retention-policy/flows/{flow_id}", {
          params: { path: { flow_id: flow.id } },
          body: {
            policy: sent === null ? null : { days: sent },
            expected_effective_days: expected,
            expected_inherited_days: expectedSpace
          }
        })
      ),
    onSuccess: async (saved) => {
      await writeAnswer<PolicySettings>(policyKey(flow.id), () => saved);
      await writeAnswer<FlowPublic>(flowKeys.flow(flow.id), (current) =>
        current ? { ...current, run_history_retention: saved.effective } : current
      );
      // The answer is the server's as of the save, and the writes cancelled any read in
      // flight: a read started now sees a later change, such as a shorter space time.
      // Not awaited: the dialog closes without waiting for the reads.
      void queryClient.invalidateQueries({ queryKey: policyKey(flow.id), exact: true });
      void queryClient.invalidateQueries({ queryKey: flowKeys.flow(flow.id), exact: true });
      toast.success(t("flows_retention_saved"));
      onClose();
    },
    onError: async (error) => {
      if (error instanceof EneoApiError && error.reason === "retention_time_changed") {
        // Changed by someone else: nothing was saved. The draft is dropped and the times are
        // read again, so the field shows the time read and a time typed again is warned
        // about against what applies now.
        toastApiError(error, t);
        setEnterHeldFor(null);
        setDraft(null);
        void queryClient.invalidateQueries({ queryKey: policyKey(flow.id), exact: true });
        void queryClient.invalidateQueries({ queryKey: flowKeys.flow(flow.id), exact: true });
        field.current?.focus();
        return;
      }
      const refusedAt = refusedCap(error);
      if (refusedAt === null) {
        toastApiError(error, t);
        return;
      }
      // The refusal names a newer space time than the one read; an empty field inherits it.
      await writeAnswer<PolicySettings>(policyKey(flow.id), (current) =>
        current ? { ...current, inherited_policy: { days: refusedAt } } : current
      );
      // The refusal is the server's as of the save, and the write cancelled any read in
      // flight: a read started now sees a later change, such as a longer space time, and the
      // section's projection, which the space time changes. Not awaited: the cap error does
      // not wait for the reads.
      void queryClient.invalidateQueries({ queryKey: policyKey(flow.id), exact: true });
      void queryClient.invalidateQueries({ queryKey: flowKeys.flow(flow.id), exact: true });
      setOverCap(true);
      field.current?.focus();
    }
  });

  // The cap error shows only while it holds: a later read may give the space a longer time.
  const problem =
    refused && days === undefined
      ? t("flows_retention_days_range", { min: 1, max: RETENTION_MAX_DAYS })
      : overCap && spaceDays !== null && typeof days === "number" && days > spaceDays
        ? t("flows_retention_cap_space", { days: spaceDays })
        : undefined;
  // What an empty field means, and the cap; an error in the field already names the cap.
  const applies = personalSpace
    ? `${t("flows_retention_personal")} ${t("flows_retention_empty_none")}`
    : spaceDays === null
      ? `${t("flows_retention_applies_none_dialog")} ${t("flows_retention_empty_none")}`
      : problem
        ? undefined
        : days === null
          ? t("flows_retention_applies_space", { days: spaceDays })
          : days === savedDays && days > spaceDays
            ? t("flows_retention_longer_saved_dialog", { days, spaceDays })
            : t("flows_retention_applies_space_cap", { days: spaceDays });
  const applied = (flowDays: number | null) =>
    automaticRemovalDays({ personalSpace, spaceDays, flowDays });
  const current = applied(savedDays);
  const next = days === undefined ? null : applied(days);
  const shortens = draft !== null && current !== null && next !== null && next < current;
  // The date the new time reaches back to: a run that finished then or earlier is due.
  const warning =
    shortens && !problem
      ? {
          title: t("flows_retention_shorter_title", {
            date: unbroken(format.dateTime(daysAgo(next), { dateStyle: "long" }))
          }),
          body: t("flows_retention_shorter_warning", { from: current, to: next })
        }
      : null;

  // Said once as the time becomes shorter; the field's description carries it after that.
  const announceWarning = useEffectEvent(() => {
    if (warning) announce(warning.title);
  });
  const warns = warning !== null;
  useEffect(() => {
    if (warns) announceWarning();
  }, [warns]);

  /**
   * Saves what the field holds. A click or a tap on "Spara och ta bort" saves, its warning
   * already on screen; the first Enter for a shorter time does not, since it may follow the
   * last digit before the warning has been read, and the next one does.
   */
  function submit(byEnter: boolean) {
    if (save.isPending) return;
    // Nothing edited is nothing to save: resending the time as read could overwrite a newer one.
    if (!draft) onClose();
    else if (days === undefined) setRefused(true);
    else if (byEnter && warning && enterHeldFor !== days) setEnterHeldFor(days);
    else
      save.mutate({
        sent: days,
        expected: settings.effective.effective_days ?? null,
        expectedSpace: spaceDays
      });
  }

  return (
    <Layout
      header={
        <DialogHeader
          title={t("flows_retention_change")}
          subtitle={subtitle}
          onOpenChange={(next) => {
            if (!next) onClose();
          }}
        />
      }
      content={
        <LayoutContent>
          <form
            id={formId}
            noValidate
            className="flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              submit(false);
            }}
          >
            <div className="flex flex-col gap-2">
              <div className="flex items-start gap-3">
                <TextInput
                  ref={field}
                  label={t("flows_retention_days_label")}
                  description={applies}
                  value={text}
                  onChange={(value) => {
                    setDraft({ text: value });
                    setOverCap(false);
                  }}
                  onKeyDown={(event) => {
                    // Enter is decided here, so a browser's implicit submit never bypasses it.
                    if (event.key !== "Enter" || event.nativeEvent.isComposing) return;
                    event.preventDefault();
                    submit(true);
                  }}
                  inputMode="numeric"
                  autoComplete="off"
                  placeholder={
                    personalSpace || spaceDays === null
                      ? undefined
                      : t("flows_retention_days_placeholder")
                  }
                  width="12rem"
                  hasClear
                  // Read-only, not disabled: it keeps focus, and a refusal marks the value sent.
                  isReadOnly={save.isPending}
                  aria-describedby={warning ? warningId : undefined}
                  status={problem ? { type: "error", message: problem } : undefined}
                />
                {/* After the field only with a value, so the placeholder reads on its own. */}
                {text.trim() === "" ? null : (
                  <span aria-hidden="true" className="text-ax-text-secondary mt-auto py-1.5">
                    {t("days")}
                  </span>
                )}
              </div>
              {spaceDays === null && spaceSettingsHref ? (
                <SpaceLink href={spaceSettingsHref}>
                  {t("flows_retention_space_link_set")}
                </SpaceLink>
              ) : null}
            </div>
            {warning ? (
              <Banner
                id={warningId}
                status="warning"
                title={warning.title}
                description={warning.body}
                collapsible={false}
              />
            ) : null}
          </form>
        </LayoutContent>
      }
      footer={
        <LayoutFooter>
          <div className="flex flex-wrap justify-end gap-2">
            <Button label={t("cancel")} isDisabled={save.isPending} onClick={onClose} />
            <Button
              type="submit"
              form={formId}
              variant={warning ? "destructive" : "primary"}
              label={warning ? t("flows_retention_save_anyway") : t("save")}
              isLoading={save.isPending}
              isInterruptible
            />
          </div>
        </LayoutFooter>
      }
    />
  );
}
