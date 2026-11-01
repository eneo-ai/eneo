"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import {
  DropdownMenu,
  DropdownMenuDivider,
  DropdownMenuItem
} from "@astryxdesign/core/DropdownMenu";
import { Heading } from "@astryxdesign/core/Heading";
import { Switch } from "@astryxdesign/core/Switch";
import { pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { Text } from "@astryxdesign/core/Text";
import { VisuallyHidden } from "@astryxdesign/core/VisuallyHidden";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AudioLines, MoreHorizontal, Pencil, Plug, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "use-intl";
import { useCallback, useId, useRef, useState, type RefObject } from "react";
import { Table } from "@/components/astryx/table";
import { ClientTime } from "@/components/composites/client-time";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { EmptyState } from "@/components/composites/empty-state";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { StatusLabel } from "@/components/composites/status-label";
import { TableFrame } from "@/components/composites/table-frame";
import type { SecurityClassification } from "@/features/admin/security-classifications/security-classifications";
import { useRemovalMutation } from "@/features/spaces/removal";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import { describeCheck } from "./transcription-service-check";
import { TranscriptionServiceDialog } from "./transcription-service-dialog";
import {
  applySavedService,
  checkTranscriptionService,
  createTranscriptionService,
  deleteTranscriptionService,
  patchService,
  TRANSCRIPTION_SERVICE_CATALOGUE_KEY,
  TRANSCRIPTION_SERVICES_KEY,
  transcriptionServicesQueryOptions,
  updateTranscriptionService,
  type TranscriptionService,
  type TranscriptionServiceCreate,
  type TranscriptionServiceUpdate
} from "./transcription-services";

/**
 * Ids with something in flight: the set as rendered, the same set for
 * callbacks (which must not wait for a render), and the setter.
 */
function useIdSet(): [
  ReadonlySet<string>,
  RefObject<ReadonlySet<string>>,
  (id: string, on: boolean) => void
] {
  const [ids, setIds] = useState<ReadonlySet<string>>(() => new Set());
  const ref = useRef(ids);
  const set = useCallback((id: string, on: boolean) => {
    if (ref.current.has(id) === on) return;
    const next = new Set(ref.current);
    if (on) next.add(id);
    else next.delete(id);
    ref.current = next;
    setIds(next);
  }, []);
  return [ids, ref, set];
}

function host(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

/**
 * The organisation's services for word timings and speaker identification
 * (such as Vemsa), on the models page. This list owns every change: each is
 * saved as it is made and applied from the response, one at a time per
 * service, so a late answer never undoes a later change or brings back a
 * removed service. The latest check is stored with the service, so every
 * administrator sees it.
 */
export function TranscriptionServicesSection({
  classifications
}: {
  classifications: SecurityClassification[];
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const query = useQuery(transcriptionServicesQueryOptions(browserApi));
  const services = query.data ?? [];

  const [checking, checkingRef, setChecking] = useIdSet();
  // Services with a change in flight; their other changes wait for it.
  const [busy, busyRef, setBusy] = useIdSet();
  // The latest check started per service; an earlier one's answer is dropped.
  const checkRuns = useRef(new Map<string, number>());

  const [dialogKey, setDialogKey] = useState(0);
  const [dialogOpen, setDialogOpen] = useState(false);
  // What the dialog opened on (read once by it), then the service it edits.
  const [dialogService, setDialogService] = useState<TranscriptionService | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [disabling, setDisabling] = useState<TranscriptionService | null>(null);
  const [disablePending, setDisablePending] = useState(false);
  const [removing, setRemoving] = useState<TranscriptionService | null>(null);

  const current = () =>
    queryClient.getQueryData<TranscriptionService[]>(TRANSCRIPTION_SERVICES_KEY);
  const has = (id: string) => current()?.some((service) => service.id === id) ?? false;
  function patch(id: string, fields: Partial<TranscriptionService>) {
    queryClient.setQueryData<TranscriptionService[]>(TRANSCRIPTION_SERVICES_KEY, (list) =>
      patchService(list, id, fields)
    );
  }
  // Space editors see the services by name; what changed here changes there.
  const refreshCatalogue = () =>
    void queryClient.invalidateQueries({ queryKey: TRANSCRIPTION_SERVICE_CATALOGUE_KEY });

  // Every check is a new run, so one started before a save never answers for
  // the saved settings.
  async function runCheck(id: string) {
    const run = (checkRuns.current.get(id) ?? 0) + 1;
    checkRuns.current.set(id, run);
    setChecking(id, true);
    try {
      const result = await checkTranscriptionService(browserApi, id);
      if (checkRuns.current.get(id) !== run || !has(id)) return;
      patch(id, { last_check: result });
      const name = current()?.find((service) => service.id === id)?.name ?? "";
      announce(
        t("speaker_service_check_announce", { name, status: describeCheck(result, t).label })
      );
    } catch (error) {
      if (checkRuns.current.get(id) === run) toastApiError(error, t);
    } finally {
      if (checkRuns.current.get(id) === run) setChecking(id, false);
    }
  }

  // Applies a saved service as the server returned it (applySavedService). A
  // check still running may have tested settings this answer replaced
  // (another administrator can have changed the key, which no answer shows),
  // so its result is dropped. A check this interrupted starts again, so
  // connecting a service as the default still shows its test; a new address
  // or key from this page starts one in `update`.
  function replace(next: TranscriptionService, marksDefault = false, newSettings = false): boolean {
    if (!has(next.id)) return false;
    queryClient.setQueryData<TranscriptionService[]>(TRANSCRIPTION_SERVICES_KEY, (list) =>
      applySavedService(list, next, marksDefault)
    );
    const interrupted = checkingRef.current.has(next.id);
    checkRuns.current.set(next.id, (checkRuns.current.get(next.id) ?? 0) + 1);
    setChecking(next.id, false);
    if (interrupted && !newSettings) void runCheck(next.id);
    refreshCatalogue();
    return true;
  }

  async function mutate<T>(id: string, change: () => Promise<T>): Promise<T> {
    setBusy(id, true);
    try {
      return await change();
    } finally {
      setBusy(id, false);
    }
  }

  async function saveEnabled(id: string, enabled: boolean) {
    replace(
      await mutate(id, () => updateTranscriptionService(browserApi, id, { is_enabled: enabled }))
    );
  }

  // Switching on, or off for a service no space uses, happens at once and is
  // undone if the save fails. Switching off a service in use asks first.
  async function setEnabled(service: TranscriptionService, enabled: boolean) {
    if (busyRef.current.has(service.id)) return;
    if (!enabled && service.space_count > 0) {
      setDisabling(service);
      return;
    }
    patch(service.id, { is_enabled: enabled });
    try {
      await saveEnabled(service.id, enabled);
    } catch (error) {
      patch(service.id, { is_enabled: !enabled });
      toastApiError(error, t);
    }
  }

  async function confirmDisable() {
    if (!disabling || disablePending) return;
    setDisablePending(true);
    try {
      await saveEnabled(disabling.id, false);
      setDisabling(null);
    } catch (error) {
      toastApiError(error, t);
    } finally {
      setDisablePending(false);
    }
  }

  // A new service is tested at once; the dialog stays open to show the result.
  async function create(body: TranscriptionServiceCreate): Promise<TranscriptionService> {
    const created = await createTranscriptionService(browserApi, body);
    queryClient.setQueryData<TranscriptionService[]>(TRANSCRIPTION_SERVICES_KEY, (list) => [
      ...(list ?? []),
      created
    ]);
    setEditingId(created.id);
    refreshCatalogue();
    void runCheck(created.id);
    return created;
  }

  // Only a new address or key changes what a check would find.
  async function update(
    id: string,
    body: TranscriptionServiceUpdate
  ): Promise<TranscriptionService> {
    const retest = "endpoint_url" in body || "api_key" in body;
    const updated = await mutate(id, () => updateTranscriptionService(browserApi, id, body));
    if (replace(updated, "is_default" in body, retest) && retest) void runCheck(id);
    return updated;
  }

  const remove = useRemovalMutation({
    mutationFn: (id: string) => mutate(id, () => deleteTranscriptionService(browserApi, id)),
    refresh: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: TRANSCRIPTION_SERVICES_KEY }),
        queryClient.invalidateQueries({ queryKey: TRANSCRIPTION_SERVICE_CATALOGUE_KEY })
      ]),
    onRemoved: (_data, id) => {
      checkRuns.current.delete(id);
      setChecking(id, false);
      setRemoving(null);
    },
    focusTarget: headingRef
  });

  function openDialog(service: TranscriptionService | null) {
    setDialogService(service);
    setEditingId(service?.id ?? null);
    setDialogKey((key) => key + 1);
    setDialogOpen(true);
  }

  const editing = editingId ? services.find((service) => service.id === editingId) : undefined;

  function spaceUsage(count: number): string {
    if (count === 0) return t("speaker_service_used_in_none");
    return count === 1
      ? t("speaker_service_used_in_one", { count })
      : t("speaker_service_used_in", { count });
  }

  const connect = (
    <Button
      label={t("speaker_service_connect")}
      icon={<Plus className="size-4" aria-hidden="true" />}
      onClick={() => openDialog(null)}
    />
  );

  const columns: TableColumn<TranscriptionService>[] = [
    {
      key: "name",
      header: t("speaker_service_column_service"),
      width: proportional(1, { minWidth: 200 }),
      renderCell: (service) => (
        <div className="flex min-w-0 flex-col gap-0.5">
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-medium break-words">{service.name}</span>
            {service.is_default && (
              <Badge variant="blue" label={t("speaker_service_default_badge")} />
            )}
          </span>
          <Text type="supporting" maxLines={1}>
            {host(service.endpoint_url)} · {spaceUsage(service.space_count)}
          </Text>
        </div>
      )
    },
    {
      key: "classification",
      header: t("speaker_service_column_classification"),
      width: pixel(144),
      renderCell: (service) =>
        service.security_classification ? (
          <Badge label={service.security_classification.name} />
        ) : (
          <span className="text-ax-text-secondary text-sm">
            {t("speaker_service_classification_none")}
          </span>
        )
    },
    {
      key: "connection",
      header: t("speaker_service_column_connection"),
      width: pixel(232),
      renderCell: (service) => {
        if (checking.has(service.id)) {
          return <StatusLabel status="accent" label={t("speaker_service_testing")} isPulsing />;
        }
        const check = service.last_check;
        if (!check) {
          return (
            <span className="text-ax-text-secondary text-sm">
              {t("speaker_service_not_tested")}
            </span>
          );
        }
        const summary = describeCheck(check, t);
        return (
          <div className="flex flex-col items-start gap-0.5">
            <StatusLabel
              status={summary.tone === "info" ? "neutral" : summary.tone}
              label={summary.label}
            />
            {/* What the service does for flows, or why it failed, then when that was seen. */}
            <Text type="supporting" size="sm">
              {summary.note ? `${summary.note} · ` : null}
              {t.rich("speaker_service_checked_at", {
                time: () => <ClientTime value={check.checked_at} format="relative" />
              })}
            </Text>
          </div>
        );
      }
    },
    {
      key: "active",
      header: t("speaker_service_column_active"),
      width: pixel(88),
      renderCell: (service) => (
        // The track centred in its 44 px touch box, level with the row's menu.
        <div className="[&>*]:flex [&>*]:items-center pointer-coarse:[&>*]:min-h-11">
          <Switch
            label={service.name}
            isLabelHidden
            value={service.is_enabled}
            // Saving, it keeps focus and ignores a press (Astryx's busy state).
            onChange={(enabled) => void setEnabled(service, enabled)}
            isLoading={busy.has(service.id)}
          />
        </div>
      )
    },
    {
      key: "actions",
      header: <VisuallyHidden>{t("actions")}</VisuallyHidden>,
      width: pixel(64),
      align: "end",
      renderCell: (service) => {
        const label = t("speaker_service_actions", { name: service.name });
        return (
          <DropdownMenu
            button={{
              label,
              tooltip: label,
              icon: <MoreHorizontal className="size-4" aria-hidden="true" />,
              isIconOnly: true,
              variant: "ghost",
              size: "sm"
            }}
            hasChevron={false}
            alignment="end"
          >
            <DropdownMenuItem
              icon={Pencil}
              label={t("edit")}
              isDisabled={busy.has(service.id)}
              onClick={() => openDialog(service)}
            />
            {/* Never disabled while it runs: another check simply starts again. */}
            <DropdownMenuItem
              icon={Plug}
              label={t("speaker_service_test")}
              onClick={() => void runCheck(service.id)}
            />
            <DropdownMenuDivider />
            <DropdownMenuItem
              icon={Trash2}
              label={t("remove")}
              variant="destructive"
              isDisabled={busy.has(service.id)}
              onClick={() => setRemoving(service)}
            />
          </DropdownMenu>
        );
      }
    }
  ];

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4 pt-4">
      <header>
        <Heading
          level={2}
          id={headingId}
          ref={headingRef}
          tabIndex={-1}
          className="focus-visible:outline-ring rounded-ax-inner text-base focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          {t("speaker_identification")}
        </Heading>
        <Text type="supporting" className="mt-1 block max-w-3xl">
          {t("speaker_service_intro")}
        </Text>
      </header>

      <QueryStateBoundary query={query} rows={2} errorTitle={t("speaker_service_list_failed")}>
        {(list) =>
          list.length === 0 ? (
            <EmptyState
              title={t("speaker_service_empty_title")}
              description={t("speaker_service_empty_description")}
              icon={<AudioLines />}
              headingLevel={3}
              actions={connect}
            />
          ) : (
            <>
              <TableFrame>
                <Table
                  data={list}
                  columns={columns}
                  idKey="id"
                  aria-labelledby={headingId}
                  pinnedColumn="name"
                  pinnedEndColumn="actions"
                  className="min-w-182"
                />
              </TableFrame>
              {/* Under the list, as the models' "Lägg till leverantör" is on its tab. */}
              <div className="flex justify-center">{connect}</div>
            </>
          )
        }
      </QueryStateBoundary>

      {dialogKey > 0 && (
        <TranscriptionServiceDialog
          key={dialogKey}
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          service={dialogService}
          classifications={classifications}
          check={editing?.last_check}
          checking={editing ? checking.has(editing.id) : false}
          onCreate={create}
          onUpdate={update}
          onTest={() => {
            if (editingId) void runCheck(editingId);
          }}
        />
      )}

      <ConfirmDialogControlled
        open={disabling !== null}
        onOpenChange={(open) => !open && setDisabling(null)}
        title={t("speaker_service_disable_title", { name: disabling?.name ?? "" })}
        description={
          disabling?.space_count === 1
            ? t("speaker_service_disable_description_one", { count: 1 })
            : t("speaker_service_disable_description", { count: disabling?.space_count ?? 0 })
        }
        confirmLabel={
          disablePending ? t("speaker_service_disabling") : t("speaker_service_disable_confirm")
        }
        variant="destructive"
        pending={disablePending}
        onConfirm={() => void confirmDisable()}
      />

      <ConfirmDialogControlled
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={t("speaker_service_delete_title", { name: removing?.name ?? "" })}
        description={
          removing && removing.space_count > 0
            ? `${spaceUsage(removing.space_count)}. ${t("speaker_service_delete_description")}`
            : t("speaker_service_delete_description")
        }
        confirmLabel={remove.isPending ? t("removing") : t("remove")}
        variant="destructive"
        pending={remove.isPending}
        onConfirm={() => {
          if (removing && !remove.isPending) remove.mutate(removing.id);
        }}
      />
    </section>
  );
}
