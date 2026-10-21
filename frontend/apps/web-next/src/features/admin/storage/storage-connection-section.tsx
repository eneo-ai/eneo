"use client";

import {
  ArrowLeftRight,
  CircleAlert,
  CircleCheck,
  ExternalLink,
  HardDrive,
  KeyRound,
  RefreshCw
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState, type SubmitEvent } from "react";
import { flushSync } from "react-dom";
import { FieldProblem, fieldProblemProps } from "@/components/composites/field-problem";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import { SettingsGroup } from "@/components/composites/settings-rows";
import type { DeploymentPolicy } from "./storage-policy";
import {
  connectionErrorKeys,
  outcomeMayBeUnknown,
  pendingOutcome,
  previousOutcome,
  type Connection,
  type ConnectionInput,
  type PreviousAction
} from "./object-store-connection";

type DialogMode = "create" | "rotate" | "switch";
type SuccessKind = DialogMode | "switch-back";
type Capability = DeploymentPolicy["capabilities"][number];
const EMPTY_INPUT: ConnectionInput = {
  endpoint_url: "",
  bucket: "",
  region: "",
  access_key_id: "",
  secret_access_key: "",
  addressing_style: "path"
};

export function StorageConnectionSection({
  capability,
  canEdit,
  onConnectionChanged,
  onAuthorityRevoked
}: {
  capability: Capability | undefined;
  canEdit: boolean;
  onConnectionChanged: () => Promise<void>;
  onAuthorityRevoked: () => void;
}) {
  const t = useTranslations();
  const [connection, setConnection] = useState<Connection | null>(null);
  const [loadStatus, setLoadStatus] = useState<"idle" | "loading" | "error">(
    canEdit ? "loading" : "idle"
  );
  const [mode, setMode] = useState<DialogMode | null>(null);
  const [input, setInput] = useState<ConnectionInput>(EMPTY_INPUT);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [previousOpen, setPreviousOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const endpointRef = useRef<HTMLInputElement>(null);
  const bucketRef = useRef<HTMLInputElement>(null);
  const regionRef = useRef<HTMLInputElement>(null);
  const accessKeyRef = useRef<HTMLInputElement>(null);
  const secretKeyRef = useRef<HTMLInputElement>(null);
  const [submissionReason, setSubmissionReason] = useState<string | null>(null);
  const [submissionFailed, setSubmissionFailed] = useState(false);
  const [mutationUnknown, setMutationUnknown] = useState(false);
  const [alreadyConfigured, setAlreadyConfigured] = useState(false);
  const [revisionConflict, setRevisionConflict] = useState(false);
  const [success, setSuccess] = useState<SuccessKind | null>(null);
  // Which action on the previous destination is running.
  const [previousBusy, setPreviousBusy] = useState<"switch-back" | "forget" | null>(null);
  const [previousReason, setPreviousReason] = useState<string | null>(null);
  const [previousFailed, setPreviousFailed] = useState(false);
  const [unresolvedPrevious, setUnresolvedPrevious] = useState<PreviousAction | null>(null);
  const [pendingBusy, setPendingBusy] = useState(false);
  const [pendingReason, setPendingReason] = useState<string | null>(null);
  const [pendingFailed, setPendingFailed] = useState(false);
  const [unresolvedPending, setUnresolvedPending] = useState<number | null>(null);

  const configured = connection?.configured ?? capability?.configured ?? false;
  const degraded = configured && capability?.readiness_code !== "ready";
  const previous = connection?.previous_destination ?? null;
  const pending = connection?.pending_destination ?? null;
  const canManage =
    canEdit &&
    loadStatus === "idle" &&
    connection?.source === "admin" &&
    connection.credentials_can_be_managed &&
    connection.revision != null;
  const canCreate =
    canEdit &&
    loadStatus === "idle" &&
    connection?.source === "unconfigured" &&
    connection.credentials_can_be_managed;
  // Every field is required; rotating the keys keeps the destination.
  const requiredProblem = (value: string) => (value.trim() ? null : t("required_field"));
  const destinationLocked = mode === "rotate";
  const problems = {
    endpoint: destinationLocked ? null : requiredProblem(input.endpoint_url),
    bucket: destinationLocked ? null : requiredProblem(input.bucket),
    region: destinationLocked ? null : requiredProblem(input.region),
    accessKey: requiredProblem(input.access_key_id),
    secretKey: input.secret_access_key ? null : t("required_field")
  };
  const shownProblem = (field: keyof typeof problems) => (submitted ? problems[field] : null);

  const readConnection = useCallback(async (): Promise<Connection | null> => {
    setLoadStatus("loading");
    try {
      const current = await unwrap(browserApi.GET("/api/v1/admin/object-store-connection"));
      setConnection(current);
      setLoadStatus("idle");
      return current;
    } catch (error) {
      if (error instanceof EneoApiError && error.status === 403) onAuthorityRevoked();
      setLoadStatus("error");
      return null;
    }
  }, [onAuthorityRevoked]);

  useEffect(() => {
    if (!canEdit) return;
    let active = true;
    queueMicrotask(() => {
      if (active) void readConnection();
    });
    return () => {
      active = false;
    };
  }, [canEdit, readConnection]);

  const reason = (error: unknown) =>
    error instanceof EneoApiError ? (error.reason ?? null) : null;
  const forbidden = (error: unknown) => error instanceof EneoApiError && error.status === 403;

  async function resolvePrevious(attempt: PreviousAction) {
    const current = await readConnection();
    if (current === null) return;
    setUnresolvedPrevious(null);
    const outcome = previousOutcome(current, attempt);
    if (outcome === "committed") {
      if (attempt.kind === "switch-back") setSuccess("switch-back");
      await onConnectionChanged();
    } else {
      setPreviousFailed(true);
      setPreviousReason(
        outcome === "not-applied"
          ? "object_store_connection_mutation_outcome_unknown"
          : "object_store_connection_revision_conflict"
      );
    }
  }

  async function resolvePending(revision: number) {
    const current = await readConnection();
    if (current === null) return;
    setUnresolvedPending(null);
    const outcome = pendingOutcome(current, revision);
    if (outcome !== "committed") {
      setPendingFailed(true);
      setPendingReason(
        outcome === "not-applied"
          ? "object_store_connection_mutation_outcome_unknown"
          : "object_store_connection_revision_conflict"
      );
    }
  }

  async function recover() {
    if (unresolvedPrevious) return resolvePrevious(unresolvedPrevious);
    if (unresolvedPending !== null) return resolvePending(unresolvedPending);
    if ((await readConnection()) && (mutationUnknown || alreadyConfigured || revisionConflict))
      await onConnectionChanged();
  }

  function openDialog(nextMode: DialogMode) {
    setMode(nextMode);
    setInput(
      nextMode === "rotate" && connection
        ? {
            endpoint_url: connection.endpoint_url ?? "",
            bucket: connection.bucket ?? "",
            region: connection.region ?? "",
            addressing_style: connection.addressing_style ?? "path",
            access_key_id: "",
            secret_access_key: ""
          }
        : EMPTY_INPUT
    );
    setAdvancedOpen(false);
    setSubmitted(false);
    setSubmissionReason(null);
    setSubmissionFailed(false);
    setMutationUnknown(false);
    setAlreadyConfigured(false);
    setRevisionConflict(false);
  }

  function closeDialog() {
    if (submitting) return;
    setMode(null);
    setInput((current) => ({ ...current, access_key_id: "", secret_access_key: "" }));
  }

  // Problems show at their fields on submit, and focus moves to the first.
  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!mode || submitting) return;
    const firstProblem = (
      [
        [problems.endpoint, endpointRef],
        [problems.bucket, bucketRef],
        [problems.region, regionRef],
        [problems.accessKey, accessKeyRef],
        [problems.secretKey, secretKeyRef]
      ] as const
    ).find(([problem]) => problem)?.[1];
    if (firstProblem) {
      // Rendered before focus moves, so the field is read with its error.
      flushSync(() => setSubmitted(true));
      firstProblem.current?.focus();
      return;
    }
    setSubmitting(true);
    setSubmissionFailed(false);
    setSubmissionReason(null);
    try {
      let updated: Connection;
      if (mode === "create") {
        updated = await unwrap(
          browserApi.POST("/api/v1/admin/object-store-connection", {
            body: {
              ...input,
              endpoint_url: input.endpoint_url.trim(),
              bucket: input.bucket.trim(),
              region: input.region.trim(),
              access_key_id: input.access_key_id.trim()
            }
          })
        );
      } else if (mode === "switch") {
        updated = await unwrap(
          browserApi.POST("/api/v1/admin/object-store-connection/destination", {
            body: {
              ...input,
              endpoint_url: input.endpoint_url.trim(),
              bucket: input.bucket.trim(),
              region: input.region.trim(),
              access_key_id: input.access_key_id.trim()
            }
          })
        );
      } else {
        if (connection?.revision == null) return;
        updated = await unwrap(
          browserApi.PUT("/api/v1/admin/object-store-connection/credentials", {
            body: {
              expected_revision: connection.revision,
              access_key_id: input.access_key_id.trim(),
              secret_access_key: input.secret_access_key
            }
          })
        );
      }
      setConnection(updated);
      setMode(null);
      setInput(EMPTY_INPUT);
      setSuccess(mode);
      setMutationUnknown(false);
      setAlreadyConfigured(false);
      setRevisionConflict(false);
      await onConnectionChanged();
    } catch (error) {
      if (forbidden(error)) {
        onAuthorityRevoked();
        setMode(null);
        setInput(EMPTY_INPUT);
      } else if (
        outcomeMayBeUnknown(error) ||
        [
          "object_store_connection_already_configured",
          "object_store_connection_revision_conflict"
        ].includes(reason(error) ?? "")
      ) {
        const failure = reason(error);
        setInput(EMPTY_INPUT);
        setMode(null);
        setSuccess(null);
        setMutationUnknown(outcomeMayBeUnknown(error));
        setAlreadyConfigured(failure === "object_store_connection_already_configured");
        setRevisionConflict(failure === "object_store_connection_revision_conflict");
        if (await readConnection()) await onConnectionChanged();
      } else {
        setSubmissionReason(reason(error));
        setSubmissionFailed(true);
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function actOnPrevious(kind: "switch-back" | "forget") {
    if (!previous || !canManage || previousBusy || unresolvedPrevious) return;
    const attempt: PreviousAction =
      kind === "switch-back"
        ? {
            kind,
            endpointUrl: previous.endpoint_url,
            bucket: previous.bucket,
            revision: previous.revision
          }
        : { kind, revision: previous.revision };
    setPreviousBusy(kind);
    setPreviousFailed(false);
    setPreviousReason(null);
    try {
      if (kind === "switch-back") {
        const updated = await unwrap(
          browserApi.POST("/api/v1/admin/object-store-connection/destination/switch-back", {
            body: { expected_previous_revision: previous.revision }
          })
        );
        setConnection(updated);
        setSuccess("switch-back");
        await onConnectionChanged();
      } else {
        await unwrap(
          browserApi.DELETE("/api/v1/admin/object-store-connection/previous", {
            params: { query: { expected_revision: previous.revision } }
          })
        );
        await readConnection();
      }
    } catch (error) {
      if (forbidden(error)) onAuthorityRevoked();
      else if (outcomeMayBeUnknown(error)) {
        setUnresolvedPrevious(attempt);
        await resolvePrevious(attempt);
      } else {
        setPreviousFailed(true);
        setPreviousReason(reason(error));
        await readConnection();
      }
    } finally {
      setPreviousBusy(null);
    }
  }

  async function abandonPending() {
    if (!pending || !canManage || pendingBusy || previousBusy || unresolvedPending !== null) return;
    const revision = pending.revision;
    setPendingBusy(true);
    setPendingFailed(false);
    setPendingReason(null);
    try {
      await unwrap(
        browserApi.DELETE("/api/v1/admin/object-store-connection/pending", {
          params: { query: { expected_revision: revision } }
        })
      );
      await readConnection();
    } catch (error) {
      if (forbidden(error)) onAuthorityRevoked();
      else if (outcomeMayBeUnknown(error)) {
        setUnresolvedPending(revision);
        await resolvePending(revision);
      } else {
        setPendingFailed(true);
        setPendingReason(reason(error));
        await readConnection();
      }
    } finally {
      setPendingBusy(false);
    }
  }

  function failureAlert(failureReason: string | null) {
    const keys = connectionErrorKeys(failureReason);
    return (
      <Alert variant="destructive" role="alert" aria-live="assertive">
        <CircleAlert className="size-4" />
        <AlertTitle>{t(keys.title as Parameters<typeof t>[0])}</AlertTitle>
        <AlertDescription>{t(keys.description as Parameters<typeof t>[0])}</AlertDescription>
      </Alert>
    );
  }

  const summary =
    loadStatus === "loading"
      ? t("storage_connection_summary_loading")
      : connection?.source === "environment"
        ? t("storage_connection_summary_environment")
        : configured
          ? t("storage_connection_summary_configured")
          : t("storage_connection_summary_unconfigured");

  return (
    <>
      <SettingsGroup
        id="storage-connection"
        title={t("storage_connection_title")}
        description={t("storage_connection_description")}
        headerEnd={
          <Badge variant={degraded ? "destructive" : configured ? "default" : "outline"}>
            {summary}
          </Badge>
        }
      >
        {success && (
          <Alert aria-live="polite">
            <CircleCheck className="size-4" />
            <AlertTitle>
              {t(
                success === "create"
                  ? "storage_connection_created_title"
                  : success === "rotate"
                    ? "storage_connection_rotated_title"
                    : success === "switch"
                      ? "storage_switch_done_title"
                      : "storage_switch_back_done_title"
              )}
            </AlertTitle>
            <AlertDescription>
              {t(
                success === "create"
                  ? "storage_connection_created_description"
                  : success === "rotate"
                    ? "storage_connection_rotated_description"
                    : success === "switch"
                      ? "storage_switch_done_description"
                      : "storage_switch_back_done_description"
              )}
            </AlertDescription>
          </Alert>
        )}
        {mutationUnknown && (
          <Alert>
            <CircleAlert className="size-4" />
            <AlertTitle>{t("storage_connection_mutation_outcome_unknown_title")}</AlertTitle>
            <AlertDescription>
              {t("storage_connection_mutation_outcome_unknown_description")}
            </AlertDescription>
          </Alert>
        )}
        {alreadyConfigured && (
          <Alert>
            <CircleCheck className="size-4" />
            <AlertTitle>{t("storage_connection_already_configured_title")}</AlertTitle>
            <AlertDescription>
              {t("storage_connection_already_configured_description")}
            </AlertDescription>
          </Alert>
        )}
        {revisionConflict &&
          loadStatus === "idle" &&
          failureAlert("object_store_connection_revision_conflict")}
        {degraded && (
          <Alert variant="destructive">
            <CircleAlert className="size-4" />
            <AlertTitle>{t("storage_connection_degraded_title")}</AlertTitle>
            <AlertDescription>
              {t("storage_connection_degraded_description", {
                status: capability ? t(`storage_readiness_${capability.readiness_code}`) : ""
              })}
            </AlertDescription>
          </Alert>
        )}

        {!canEdit ? (
          <div className="space-y-1 text-sm">
            <p className="font-medium">
              {t(
                capability?.configured
                  ? "storage_connection_health_configured"
                  : "storage_connection_health_unconfigured"
              )}
            </p>
            <p className="text-muted-foreground">
              {capability
                ? t(`storage_readiness_${capability.readiness_code}`)
                : t("storage_connection_health_unknown")}
            </p>
            <p className="text-muted-foreground text-xs">
              {t("storage_connection_storage_admin_only")}
            </p>
          </div>
        ) : loadStatus === "loading" ? (
          <div className="space-y-3" aria-busy="true">
            <Skeleton className="h-5 w-52" />
            <Skeleton className="h-16 w-full" />
            <span className="sr-only">{t("storage_connection_loading")}</span>
          </div>
        ) : loadStatus === "error" ? (
          <Alert variant="destructive">
            <CircleAlert className="size-4" />
            <AlertTitle>{t("storage_connection_load_error_title")}</AlertTitle>
            <AlertDescription>
              <p>{t("storage_connection_load_error_description")}</p>
              <Button variant="outline" size="sm" className="mt-3" onClick={() => void recover()}>
                {t("retry")}
              </Button>
            </AlertDescription>
          </Alert>
        ) : connection?.source === "admin" ? (
          <div className="space-y-5">
            <dl className="grid gap-4 sm:grid-cols-2">
              <ConnectionDetail
                label={t("storage_connection_endpoint")}
                value={connection.endpoint_url}
              />
              <ConnectionDetail label={t("storage_connection_bucket")} value={connection.bucket} />
              <ConnectionDetail label={t("storage_connection_region")} value={connection.region} />
              <ConnectionDetail
                label={t("storage_connection_addressing_style")}
                value={t(
                  connection.addressing_style === "virtual"
                    ? "storage_connection_addressing_virtual"
                    : "storage_connection_addressing_path"
                )}
              />
            </dl>
            <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
              <p className="text-muted-foreground max-w-2xl text-sm">
                {t("storage_connection_rotation_description")}
              </p>
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  disabled={!canManage}
                  onClick={() => openDialog("rotate")}
                >
                  <KeyRound className="size-4" />
                  {t("storage_connection_rotate_action")}
                </Button>
                <Button
                  variant="outline"
                  disabled={!canManage}
                  onClick={() => openDialog("switch")}
                >
                  <ArrowLeftRight className="size-4" />
                  {t("storage_switch_action")}
                </Button>
              </div>
            </div>
            {previous && (
              <div className="rounded-lg border">
                <button
                  type="button"
                  className="flex w-full items-center justify-between gap-3 p-4 text-left text-sm font-medium"
                  aria-expanded={previousOpen}
                  onClick={() => setPreviousOpen((open) => !open)}
                >
                  {t("storage_switch_previous_title")}{" "}
                  <span className="text-muted-foreground truncate">{previous.bucket}</span>
                </button>
                {previousOpen && (
                  <div className="space-y-3 border-t p-4">
                    <p className="text-muted-foreground text-sm break-all">
                      {previous.endpoint_url} · {previous.bucket}
                    </p>
                    <p className="text-muted-foreground text-sm">
                      {t("storage_switch_previous_description")}
                    </p>
                    {previousFailed && failureAlert(previousReason)}
                    {unresolvedPrevious && (
                      <Button variant="outline" onClick={() => void recover()}>
                        <RefreshCw className="size-4" />
                        {t("retry")}
                      </Button>
                    )}
                    {/* Busy, an action stays enabled so it keeps focus; presses while
                        one runs are ignored (actOnPrevious, abandonPending). */}
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="outline"
                        disabled={!canManage || unresolvedPrevious !== null}
                        aria-busy={previousBusy === "switch-back" || undefined}
                        onClick={() => void actOnPrevious("switch-back")}
                      >
                        {t("storage_switch_back_action")}
                      </Button>
                      <Button
                        variant="ghost"
                        disabled={!canManage || unresolvedPrevious !== null}
                        aria-busy={previousBusy === "forget" || undefined}
                        onClick={() => void actOnPrevious("forget")}
                      >
                        {t("storage_switch_forget_action")}
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            )}
            {pending && (
              <div className="space-y-3 rounded-lg border p-4">
                <p className="text-sm font-medium">{t("storage_pending_title")}</p>
                <p className="text-muted-foreground text-sm break-all">
                  {pending.endpoint_url} · {pending.bucket}
                </p>
                <p className="text-muted-foreground text-sm">{t("storage_pending_description")}</p>
                {pendingFailed && failureAlert(pendingReason)}
                {unresolvedPending !== null && (
                  <Button variant="outline" onClick={() => void recover()}>
                    <RefreshCw className="size-4" />
                    {t("retry")}
                  </Button>
                )}
                <Button
                  variant="ghost"
                  // eslint-disable-next-line eneo/no-busy-disabled-button -- unresolvedPending is an earlier abandon whose outcome is unknown until Retry (above) reads it, not work this button runs.
                  disabled={!canManage || unresolvedPending !== null}
                  aria-busy={pendingBusy || undefined}
                  onClick={() => void abandonPending()}
                >
                  {t("storage_pending_abandon_action")}
                </Button>
              </div>
            )}
          </div>
        ) : connection?.source === "environment" ? (
          <Alert>
            <HardDrive className="size-4" />
            <AlertTitle>{t("storage_connection_environment_title")}</AlertTitle>
            <AlertDescription>{t("storage_connection_environment_description")}</AlertDescription>
          </Alert>
        ) : (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-sm font-medium">{t("storage_connection_empty_title")}</p>
                <p className="text-muted-foreground text-sm">
                  {t("storage_connection_empty_description")}
                </p>
              </div>
              <Button disabled={!canCreate} onClick={() => openDialog("create")}>
                {t("storage_connection_add_action")}
              </Button>
            </div>
            {connection && !connection.credentials_can_be_managed && (
              <Alert>
                <CircleAlert className="size-4" />
                <AlertTitle>{t("storage_connection_encryption_required_title")}</AlertTitle>
                <AlertDescription>
                  {t("storage_connection_encryption_required_description")}
                </AlertDescription>
              </Alert>
            )}
          </div>
        )}
      </SettingsGroup>

      <Dialog
        open={mode !== null}
        onOpenChange={(open) => {
          if (!open) closeDialog();
        }}
      >
        <DialogContent
          showCloseButton={!submitting}
          className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-2xl"
        >
          <DialogHeader>
            <DialogTitle>
              {t(
                mode === "create"
                  ? "storage_connection_dialog_create_title"
                  : mode === "switch"
                    ? "storage_switch_dialog_title"
                    : "storage_connection_dialog_rotate_title"
              )}
            </DialogTitle>
            <DialogDescription>
              {t(
                mode === "create"
                  ? "storage_connection_dialog_create_description"
                  : mode === "switch"
                    ? "storage_switch_dialog_description"
                    : "storage_connection_dialog_rotate_description"
              )}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={(event) => void submit(event)} noValidate className="space-y-5">
            {submissionFailed && failureAlert(submissionReason)}
            {mode === "switch" && (
              <Alert>
                <CircleAlert className="size-4" />
                <AlertTitle>{t("storage_switch_checklist_title")}</AlertTitle>
                <AlertDescription>
                  <ul className="ml-4 list-disc space-y-1">
                    <li>{t("storage_switch_checklist_copied")}</li>
                    <li>{t("storage_switch_checklist_inline")}</li>
                    <li>{t("storage_switch_checklist_reversible")}</li>
                  </ul>
                  <a
                    className="mt-2 inline-flex items-center gap-1 underline"
                    target="_blank"
                    rel="noreferrer"
                    href="https://docs.eneo.ai/guides/object-content-storage#move-to-another-s3-compatible-service"
                  >
                    {t("storage_switch_guide_link")}
                    <ExternalLink className="size-3" />
                  </a>
                </AlertDescription>
              </Alert>
            )}
            {mode === "rotate" ? (
              <div className="space-y-2 border-b pb-4">
                <p className="text-sm font-medium">{t("storage_connection_current_destination")}</p>
                <p className="text-muted-foreground text-sm break-all">
                  {input.endpoint_url} · {input.bucket}
                </p>
                <p className="text-muted-foreground text-sm">
                  {t("storage_connection_destination_locked_help")}
                </p>
              </div>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2">
                <ConnectionField
                  id="object-store-endpoint"
                  problem={shownProblem("endpoint")}
                  label={t("storage_connection_endpoint")}
                  help={t("storage_connection_endpoint_help")}
                  className="sm:col-span-2"
                >
                  <Input
                    ref={endpointRef}
                    id="object-store-endpoint"
                    {...fieldProblemProps(
                      "object-store-endpoint",
                      shownProblem("endpoint"),
                      "object-store-endpoint-help"
                    )}
                    type="url"
                    autoComplete="url"
                    required
                    disabled={submitting}
                    placeholder={t("storage_connection_endpoint_placeholder")}
                    value={input.endpoint_url}
                    onChange={(event) =>
                      setInput((current) => ({ ...current, endpoint_url: event.target.value }))
                    }
                  />
                </ConnectionField>
                <ConnectionField
                  id="object-store-bucket"
                  problem={shownProblem("bucket")}
                  label={t("storage_connection_bucket")}
                >
                  <Input
                    ref={bucketRef}
                    id="object-store-bucket"
                    {...fieldProblemProps("object-store-bucket", shownProblem("bucket"))}
                    autoComplete="off"
                    required
                    disabled={submitting}
                    placeholder={t("storage_connection_bucket_placeholder")}
                    value={input.bucket}
                    onChange={(event) =>
                      setInput((current) => ({ ...current, bucket: event.target.value }))
                    }
                  />
                </ConnectionField>
                <ConnectionField
                  id="object-store-region"
                  problem={shownProblem("region")}
                  label={t("storage_connection_region")}
                  help={t("storage_connection_region_help")}
                >
                  <Input
                    ref={regionRef}
                    id="object-store-region"
                    {...fieldProblemProps(
                      "object-store-region",
                      shownProblem("region"),
                      "object-store-region-help"
                    )}
                    autoComplete="off"
                    required
                    disabled={submitting}
                    placeholder={t("storage_connection_region_placeholder")}
                    value={input.region}
                    onChange={(event) =>
                      setInput((current) => ({ ...current, region: event.target.value }))
                    }
                  />
                </ConnectionField>
              </div>
            )}
            <div className="grid gap-4 sm:grid-cols-2">
              <ConnectionField
                id="object-store-access-key"
                problem={shownProblem("accessKey")}
                label={t("storage_connection_access_key")}
                help={t("storage_connection_access_key_help")}
              >
                <Input
                  ref={accessKeyRef}
                  id="object-store-access-key"
                  {...fieldProblemProps(
                    "object-store-access-key",
                    shownProblem("accessKey"),
                    "object-store-access-key-help"
                  )}
                  autoComplete="off"
                  required
                  disabled={submitting}
                  value={input.access_key_id}
                  onChange={(event) =>
                    setInput((current) => ({ ...current, access_key_id: event.target.value }))
                  }
                />
              </ConnectionField>
              <ConnectionField
                id="object-store-secret-key"
                problem={shownProblem("secretKey")}
                label={t("storage_connection_secret_key")}
                help={t("storage_connection_secret_key_help")}
              >
                <Input
                  ref={secretKeyRef}
                  id="object-store-secret-key"
                  {...fieldProblemProps(
                    "object-store-secret-key",
                    shownProblem("secretKey"),
                    "object-store-secret-key-help"
                  )}
                  type="password"
                  autoComplete="new-password"
                  required
                  disabled={submitting}
                  value={input.secret_access_key}
                  onChange={(event) =>
                    setInput((current) => ({ ...current, secret_access_key: event.target.value }))
                  }
                />
              </ConnectionField>
            </div>
            {mode !== "rotate" && (
              <div className="space-y-3">
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  aria-expanded={advancedOpen}
                  onClick={() => setAdvancedOpen((open) => !open)}
                >
                  {t("storage_connection_advanced")}
                </Button>
                {advancedOpen && (
                  <ConnectionField
                    id="object-store-addressing"
                    label={t("storage_connection_addressing_style")}
                    help={t("storage_connection_addressing_help")}
                  >
                    <select
                      id="object-store-addressing"
                      className="border-input bg-background h-9 w-full rounded-md border px-3 text-sm"
                      disabled={submitting}
                      value={input.addressing_style}
                      onChange={(event) =>
                        setInput((current) => ({
                          ...current,
                          addressing_style: event.target.value === "virtual" ? "virtual" : "path"
                        }))
                      }
                    >
                      <option value="path">{t("storage_connection_addressing_path")}</option>
                      <option value="virtual">{t("storage_connection_addressing_virtual")}</option>
                    </select>
                  </ConnectionField>
                )}
              </div>
            )}
            <div className="bg-muted/50 rounded-lg p-3 text-sm">
              <p className="font-medium">
                {t(
                  mode === "rotate"
                    ? "storage_connection_probe_rotate_title"
                    : "storage_connection_probe_create_title"
                )}
              </p>
              <p className="text-muted-foreground mt-1">
                {t(
                  mode === "rotate"
                    ? "storage_connection_probe_rotate_description"
                    : mode === "switch"
                      ? "storage_switch_probe_description"
                      : "storage_connection_probe_create_description"
                )}
              </p>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" disabled={submitting} onClick={closeDialog}>
                {t("cancel")}
              </Button>
              {/* Never disabled: busy, it keeps focus and a second press is ignored. */}
              <Button type="submit" aria-busy={submitting}>
                {submitting
                  ? t("storage_connection_testing")
                  : t(
                      mode === "create"
                        ? "storage_connection_test_and_save"
                        : mode === "switch"
                          ? "storage_switch_test_and_switch"
                          : "storage_connection_test_and_rotate"
                    )}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}

function ConnectionDetail({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="min-w-0">
      <dt className="text-muted-foreground text-sm">{label}</dt>
      <dd className="mt-1 text-sm font-medium break-all" title={value ?? ""}>
        {value}
      </dd>
    </div>
  );
}

/**
 * A labelled field with its problem after a submit and its help. The control
 * (children) points at both: fieldProblemProps(id, problem, `${id}-help`).
 */
function ConnectionField({
  id,
  label,
  help,
  problem = null,
  className,
  children
}: {
  id: string;
  label: string;
  help?: string;
  problem?: string | null;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={`space-y-1.5 ${className ?? ""}`}>
      <Label htmlFor={id}>{label}</Label>
      {children}
      <FieldProblem id={id} problem={problem} />
      {help && (
        <p id={`${id}-help`} className="text-muted-foreground text-xs">
          {help}
        </p>
      )}
    </div>
  );
}
