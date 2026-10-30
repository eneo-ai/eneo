"use client";

import { useAnnounce } from "@astryxdesign/core/hooks";
import { createFlowRuntimeUploadTimeoutController } from "@eneo/eneo-js/flows/runtime-upload-policy";
import { useLocale, useTranslations } from "use-intl";
import { useEffect, useRef, useState } from "react";
import { API_BASE, onBrowserApiRequest, onRawRefusal } from "@/lib/api/base";
import { apiErrorFromResponse, EneoApiError } from "@/lib/api/errors";
import { formatBytes } from "@/lib/format";
import type { Schema } from "@/lib/api/models";
import { UploadRetries } from "./recording/upload-retry";
import type { RecordingPartInfo, UploadEntry, UploadsByStep } from "./run-contract";
import { refusalText, type Translator } from "./run-messages";
import { deleteRuntimeFile, type RuntimeInput, type UploadedFile } from "./runs-api";

type UploadPolicy = Schema<"FlowRuntimeUploadPolicyPublic">;

/** Whether a file's type is one the step takes (`type/*` covers the family). */
export function acceptsType(accepted: readonly string[], mimetype: string): boolean {
  if (accepted.length === 0) return true;
  const type = mimetype.split(";", 1)[0]?.trim().toLowerCase() ?? "";
  if (!type) return false;
  return accepted.some((entry) => {
    const allowed = entry.toLowerCase();
    return allowed.endsWith("/*") ? type.startsWith(allowed.slice(0, -1)) : type === allowed;
  });
}

/**
 * Sends one file to a step's runtime upload endpoint with the app's session,
 * reporting progress. XHR rather than fetch, because the core's timeout policy
 * keeps an upload alive while its bytes keep moving, and only XHR reports them.
 */
async function sendFile(
  flowId: string,
  stepId: string,
  file: File,
  policy: UploadPolicy | undefined,
  onProgress: (share: number) => void,
  abort: AbortController
): Promise<UploadedFile> {
  const url = `${API_BASE}/api/v1/flows/${encodeURIComponent(flowId)}/steps/${encodeURIComponent(stepId)}/runtime-files/`;
  const request = await onBrowserApiRequest({
    request: new Request(new URL(url, window.location.href), {
      method: "POST",
      headers: { accept: "application/json" },
      signal: abort.signal
    })
  });
  request.signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const timeout = createFlowRuntimeUploadTimeoutController({
      fileSizeBytes: file.size,
      policy,
      abortController: abort,
      onTimeout: () => reject(new UploadTimeoutError())
    });
    const cancel = () => xhr.abort();
    const clear = () => {
      timeout.clear();
      request.signal.removeEventListener("abort", cancel);
    };
    request.signal.addEventListener("abort", cancel, { once: true });
    xhr.upload.onprogress = (event) => {
      timeout.onProgress(event);
      if (event.lengthComputable && event.total > 0) onProgress(event.loaded / event.total);
    };
    xhr.onload = () => {
      clear();
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        // A body that is not JSON leaves only the status to go on.
      }
      const response = new Response(xhr.responseText || null, {
        status: xhr.status,
        headers: new Headers(
          xhr
            .getAllResponseHeaders()
            .trim()
            .split(/[\r\n]+/)
            .filter(Boolean)
            .map((line): [string, string] => {
              const separator = line.indexOf(":");
              return [line.slice(0, separator).trim(), line.slice(separator + 1).trim()];
            })
        )
      });
      void onRawRefusal(response, url)
        .then(() => {
          if (response.ok) resolve(body as UploadedFile);
          else reject(apiErrorFromResponse(response, body));
        })
        .catch(reject);
    };
    xhr.onerror = () => {
      clear();
      reject(new UploadNetworkError());
    };
    xhr.onabort = () => {
      clear();
      reject(request.signal.reason ?? new DOMException("Upload aborted", "AbortError"));
    };
    const body = new FormData();
    body.append("upload_file", file);
    try {
      xhr.open("POST", url);
      request.headers.forEach((value, name) => xhr.setRequestHeader(name, value));
      xhr.send(body);
    } catch (error) {
      clear();
      reject(error);
    }
  });
}

/** Deletes an upload no run will use; the core also sweeps orphans, so a failure is not news. */
function forgetRuntimeFile(flowId: string, fileId: string) {
  void deleteRuntimeFile(flowId, fileId).catch(() => {});
}

class UploadTimeoutError extends Error {
  constructor() {
    super("The upload stopped making progress");
    this.name = "UploadTimeoutError";
  }
}

class UploadNetworkError extends Error {
  constructor() {
    super("The upload could not reach the server");
    this.name = "UploadNetworkError";
  }
}

/** A failure that may pass: the same file can be sent again (the network, a timeout, a busy server). */
function passes(error: unknown): boolean {
  if (error instanceof UploadTimeoutError || error instanceof UploadNetworkError) return true;
  return (
    error instanceof EneoApiError &&
    (error.status === 408 || error.status === 429 || error.status >= 500)
  );
}

function uploadProblem(error: unknown, input: RuntimeInput, t: Translator, locale: string) {
  if (error instanceof UploadTimeoutError) return t("flow_runs_upload_stalled");
  if (error instanceof UploadNetworkError) return t("flow_runs_upload_network");
  if (error instanceof EneoApiError && error.status === 413 && input.max_file_size_bytes) {
    return t("flow_runs_upload_too_large", {
      max: formatBytes(input.max_file_size_bytes, locale)
    });
  }
  return refusalText(error, t);
}

/** What else a file added to the form is: a recording's part, with the name the form shows. */
export type AddedFileInfo = { recording?: RecordingPartInfo; label?: string };

/**
 * The files of a run form, per step, from the moment they are picked until
 * the run starts. Each file uploads as soon as it is picked; one the step
 * cannot take (type, size, count) is refused before any byte is sent. A file
 * removed from the form, or left behind when the form closes without
 * starting a run, is deleted again, since nothing else would ever use it.
 * Files the started run took (`claim`) stay.
 *
 * A failed upload keeps its file, so it can be sent again (`retry`); a
 * recording made in the form exists nowhere else, so a part whose upload
 * failed for a reason that passes is sent again by itself after growing
 * waits, and at once when the browser is back online (`UploadRetries`).
 */
export function useRuntimeUploads(flowId: string, policy: UploadPolicy | undefined) {
  const t = useTranslations();
  const locale = useLocale();
  const announce = useAnnounce();
  const [uploads, setUploads] = useState<UploadsByStep>({});
  const current = useRef<UploadsByStep>({});
  const inFlight = useRef(new Map<string, AbortController>());
  const files = useRef(new Map<string, { input: RuntimeInput; file: File }>());
  const claimed = useRef(false);
  const mounted = useRef(true);
  // Created once; an automatic attempt sends through the latest render's `send`.
  const latestSend = useRef<(stepId: string, key: string) => void>(() => undefined);
  const [retries] = useState(
    () =>
      new UploadRetries((key) => {
        const kept = files.current.get(key);
        if (kept) latestSend.current(kept.input.step_id, key);
      })
  );

  function replace(next: UploadsByStep) {
    current.current = next;
    if (mounted.current) setUploads(next);
  }

  function update(stepId: string, key: string, change: Partial<UploadEntry>) {
    const entries = current.current[stepId] ?? [];
    if (!entries.some((entry) => entry.key === key)) return false;
    replace({
      ...current.current,
      [stepId]: entries.map((entry) => (entry.key === key ? { ...entry, ...change } : entry))
    });
    return true;
  }

  function forget(fileId: string) {
    forgetRuntimeFile(flowId, fileId);
  }

  useEffect(() => {
    mounted.current = true;
    const controllers = inFlight.current;
    const entriesNow = current;
    return () => {
      mounted.current = false;
      retries.dispose();
      for (const controller of controllers.values()) controller.abort();
      controllers.clear();
      if (claimed.current) return;
      for (const entries of Object.values(entriesNow.current)) {
        for (const entry of entries) if (entry.fileId) forgetRuntimeFile(flowId, entry.fileId);
      }
    };
  }, [flowId, retries]);

  async function upload(input: RuntimeInput, entry: UploadEntry, file: File) {
    const abort = new AbortController();
    inFlight.current.set(entry.key, abort);
    try {
      const stored = await sendFile(
        flowId,
        input.step_id,
        file,
        policy,
        (progress) => update(input.step_id, entry.key, { progress }),
        abort
      );
      retries.reset(entry.key);
      if (
        update(input.step_id, entry.key, {
          state: "done",
          fileId: stored.id,
          progress: 1,
          problem: undefined,
          retryable: undefined,
          nextRetryAt: undefined
        })
      ) {
        // Stored: nothing will send it again. A recording's part stays, so it
        // can still be saved as a file: it exists nowhere else on the device.
        if (!entry.recording) files.current.delete(entry.key);
        announce(t("flow_runs_upload_finished", { name: entry.name }));
      } else {
        // Removed while it was uploading: the stored file is not wanted.
        forget(stored.id);
      }
    } catch (error) {
      if (abort.signal.aborted && !(error instanceof UploadTimeoutError)) return;
      const retryable = passes(error);
      // A recorded part goes again by itself; a picked file waits for the person.
      const nextRetryAt = entry.recording && retryable ? retries.failed(entry.key) : undefined;
      const failed = update(input.step_id, entry.key, {
        state: "failed",
        problem: uploadProblem(error, input, t, locale),
        retryable,
        nextRetryAt
      });
      if (failed) announce(t("flow_runs_upload_failed", { name: entry.name }));
      else retries.reset(entry.key);
    } finally {
      inFlight.current.delete(entry.key);
    }
  }

  /** Takes picked files for a step: uploads those it can take, refuses the rest at once. */
  function add(input: RuntimeInput, picked: readonly File[], info: AddedFileInfo = {}) {
    const existing = current.current[input.step_id] ?? [];
    let slots =
      input.max_files == null
        ? Infinity
        : input.max_files - existing.filter((entry) => entry.state !== "failed").length;
    const started: { entry: UploadEntry; file: File }[] = [];
    const added = picked.map((file): UploadEntry => {
      const base = {
        key: crypto.randomUUID(),
        name: info.label ?? file.name,
        size: file.size,
        mimetype: file.type,
        ...(info.recording ? { recording: info.recording } : {})
      };
      // A recording's part is kept even when it is refused: it exists nowhere else.
      if (info.recording) files.current.set(base.key, { input, file });
      const refuse = (problem: string): UploadEntry => ({ ...base, state: "failed", problem });
      if (file.size === 0) return refuse(t("flow_error_flow_runtime_file_empty"));
      if (!acceptsType(input.accepted_mimetypes ?? [], file.type)) {
        return refuse(t("flow_runs_upload_wrong_type"));
      }
      if (input.max_file_size_bytes != null && file.size > input.max_file_size_bytes) {
        return refuse(
          t("flow_runs_upload_too_large", { max: formatBytes(input.max_file_size_bytes, locale) })
        );
      }
      if (slots <= 0) {
        return refuse(t("flow_runs_upload_too_many", { count: input.max_files ?? 0 }));
      }
      slots -= 1;
      const entry: UploadEntry = { ...base, state: "uploading", progress: 0 };
      files.current.set(entry.key, { input, file });
      started.push({ entry, file });
      return entry;
    });
    replace({ ...current.current, [input.step_id]: [...existing, ...added] });
    for (const { entry, file } of started) void upload(input, entry, file);
    return added;
  }

  /** Takes a file off the form: stops its upload, or deletes it if it was stored. */
  function remove(stepId: string, key: string) {
    const entry = current.current[stepId]?.find((candidate) => candidate.key === key);
    if (!entry) return;
    inFlight.current.get(key)?.abort();
    retries.reset(key);
    files.current.delete(key);
    if (entry.fileId) forget(entry.fileId);
    replace({
      ...current.current,
      [stepId]: (current.current[stepId] ?? []).filter((candidate) => candidate.key !== key)
    });
  }

  /** Sends a failed file again, when the step still has room for it; its automatic waits start over. */
  function retry(stepId: string, key: string) {
    retries.reset(key);
    send(stepId, key);
  }

  function send(stepId: string, key: string) {
    const entry = current.current[stepId]?.find((candidate) => candidate.key === key);
    const kept = files.current.get(key);
    if (!entry || entry.state !== "failed" || !kept) return;
    const { input, file } = kept;
    const taken = (current.current[stepId] ?? []).filter(
      (candidate) => candidate.state !== "failed"
    ).length;
    if (input.max_files != null && taken >= input.max_files) {
      retries.reset(key);
      update(stepId, key, {
        problem: t("flow_runs_upload_too_many", { count: input.max_files }),
        retryable: false,
        nextRetryAt: undefined
      });
      return;
    }
    update(stepId, key, {
      state: "uploading",
      progress: 0,
      problem: undefined,
      nextRetryAt: undefined
    });
    void upload(input, { ...entry, state: "uploading" }, file);
  }

  useEffect(() => {
    latestSend.current = send;
  });

  /** The file behind an entry, while the form keeps it (a recording's part, a failed upload). */
  function fileOf(key: string): File | null {
    return files.current.get(key)?.file ?? null;
  }

  // Back online: a recording's parts waiting for their next attempt go now.
  useEffect(() => {
    const resend = () => retries.online();
    window.addEventListener("online", resend);
    return () => window.removeEventListener("online", resend);
  }, [retries]);

  /** The run took the files: leaving the form no longer deletes them. */
  function claim() {
    claimed.current = true;
  }

  return { uploads, add, remove, retry, fileOf, claim };
}
