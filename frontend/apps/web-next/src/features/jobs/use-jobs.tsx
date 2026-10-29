"use client";

import { useAnnounce } from "@astryxdesign/core/hooks";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "@/lib/navigation";
import { useTranslations } from "next-intl";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore
} from "react";
import { API_BASE, onBrowserApiRequest, onRawRefusal } from "@/lib/api/base";
import { browserApi } from "@/lib/api/browser";
import { apiErrorFromResponse, getErrorMessage, unwrap } from "@/lib/api/errors";
import { pollWhile } from "@/lib/api/query";
import { useBeforeUnloadWarning } from "@/lib/hooks/use-before-unload-warning";
import { toast } from "@/lib/toast";
import {
  pendingImports,
  reportImports,
  type SettledImport
} from "@/features/knowledge/integrations/import-completion";
import { pendingSyncs, untrackSyncs } from "@/features/knowledge/integrations/pending-syncs";
import { subscribeJobEvents, useJobEventsConnected } from "./job-events";
import { describeJobOutcome } from "./job-feedback";
import { invalidateAfterJobs } from "./job-invalidation";
import {
  diffJobs,
  EMPTY_LEDGER,
  isJobOver,
  rememberActiveJob,
  type JobLedger
} from "./job-transitions";
import { isJobActive, JOBS_KEY, type Job } from "./jobs";
import { recordFinishedJob } from "./recent-results";

export { isJobActive, type Job } from "./jobs";

export type Upload = {
  id: string;
  file: File;
  status: "queued" | "uploading" | "completed" | "failed";
  /** Destination collection for this file. */
  collectionId: string;
  /** 0-100; bytes sent to the proxy, the closest the browser can observe. */
  progress: number;
  errorMessage?: string;
};

const SLOW_POLL_MS = 30_000;
const FAST_POLL_MS = 2_000;
/** Poll fast for this long after a job is registered, then fall back. */
const FAST_POLL_WINDOW_MS = 15_000;
const MAX_UPLOAD_CONNECTIONS = 5;

/** The client-side upload queue, as a store the job indicator subscribes to. */
type UploadStore = {
  subscribe: (listener: () => void) => () => void;
  getSnapshot: () => Upload[];
  set: (uploads: Upload[]) => void;
};

const NO_UPLOADS: Upload[] = [];

/** Not on the server yet: a reload would lose it. */
const isUploadPending = (upload: Upload) =>
  upload.status === "queued" || upload.status === "uploading";

function createUploadStore(): UploadStore {
  let uploads = NO_UPLOADS;
  const listeners = new Set<() => void>();
  return {
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getSnapshot: () => uploads,
    set: (next) => {
      uploads = next;
      listeners.forEach((listener) => listener());
    }
  };
}

/*
 * Only actions, which hold still: the provider sits above every page, and a
 * context that changes while React is still hydrating a page (the jobs
 * arriving, an upload's progress) makes React throw the page's server HTML
 * away and render it again. The job indicator reads jobs and uploads itself
 * (useJobActivity).
 */
type JobsContextValue = {
  /**
   * Register a backend job: switches to fast polling for quick feedback.
   * Pass the job the call returned (or every job, for calls made together) so
   * its completion is caught even when the first poll already reports it
   * finished (see job-transitions.ts).
   */
  trackJob: (job?: Job | Job[]) => void;
  /** Queue files for upload into a collection. */
  queueUploads: (collectionId: string, files: File[]) => void;
  clearFinishedUploads: () => void;
  uploadStore: UploadStore;
  /** The jobs query's fetcher; every reader of the list shares it. */
  listJobs: () => Promise<Job[]>;
};

const JobsContext = createContext<JobsContextValue | null>(null);

async function uploadInfoBlob(
  collectionId: string,
  file: File,
  onProgress: (progress: number) => void
): Promise<Job> {
  // XMLHttpRequest instead of browserApi: fetch cannot observe upload
  // progress. Request preparation and response checks still use the API seam.
  const url = `${API_BASE}/api/v1/groups/${encodeURIComponent(collectionId)}/info-blobs/upload/`;
  const request = await onBrowserApiRequest({
    request: new Request(new URL(url, window.location.href), { method: "POST" })
  });
  return new Promise<Job>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    request.headers.forEach((value, name) => xhr.setRequestHeader(name, value));
    xhr.responseType = "json";
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && event.total > 0) {
        onProgress(Math.floor((event.loaded / event.total) * 100));
      }
    });
    xhr.addEventListener("load", () => {
      const response = new Response(JSON.stringify(xhr.response ?? null), {
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
          if (response.ok) resolve(xhr.response as Job);
          else reject(apiErrorFromResponse(response, xhr.response));
        })
        .catch(reject);
    });
    xhr.addEventListener("error", () => reject(new Error("Network error")));
    const abort = () => xhr.abort();
    xhr.addEventListener("abort", () =>
      reject(request.signal.reason ?? new DOMException("Upload cancelled", "AbortError"))
    );
    xhr.addEventListener("loadend", () => request.signal.removeEventListener("abort", abort));
    request.signal.throwIfAborted();
    request.signal.addEventListener("abort", abort, { once: true });
    const body = new FormData();
    body.append("file", file);
    xhr.send(body);
  });
}

// One empty list until the jobs load.
const NO_JOBS: Job[] = [];

const fetchJobs = async (): Promise<Job[]> => (await unwrap(browserApi.GET("/api/v1/jobs/"))).items;

export function JobsProvider({ children }: { children: React.ReactNode }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const announce = useAnnounce();
  const router = useRouter();

  const fastPollUntil = useRef(0);
  // Set by the fetcher, not by the cache: a pushed update can fill the cache
  // before the first list arrives, and only a list says which jobs are gone.
  const listReceived = useRef(false);
  const listJobs = useCallback(async () => {
    const items = await fetchJobs();
    listReceived.current = true;
    return items;
  }, []);

  // The live feed (job-events.ts) delivers every status change the moment it
  // is committed. Polling stays as the safety net: slow while the feed is
  // open, fast while it is down and something is running or was just started.
  const live = useJobEventsConnected();
  const { data: jobs, dataUpdatedAt: jobsUpdatedAt } = useQuery({
    queryKey: JOBS_KEY,
    queryFn: listJobs,
    refetchInterval: pollWhile(
      // Read to schedule the next fetch, never for what renders.
      // eslint-disable-next-line react-hooks/refs, react-hooks/purity
      (items) => !live && (Date.now() < fastPollUntil.current || !!items?.some(isJobActive)),
      FAST_POLL_MS,
      SLOW_POLL_MS
    )
  });
  useEffect(
    () =>
      subscribeJobEvents(
        (job) => {
          // A pushed update goes straight into the cached list; the snapshot
          // effect below then treats it like a poll that saw the change.
          queryClient.setQueryData<Job[]>(JOBS_KEY, (current = NO_JOBS) =>
            current.some((item) => item.id === job.id)
              ? current.map((item) => (item.id === job.id ? job : item))
              : [...current, job]
          );
        },
        () => {
          void queryClient.invalidateQueries({ queryKey: JOBS_KEY });
        }
      ),
    [queryClient]
  );

  // Each snapshot is compared with the last one: a job that was active and
  // now has an outcome gets a toast (which speaks it) and a row highlight, and
  // the data it produced is refreshed. An import's first sync is told with
  // its counts instead, once its item is read (import-completion.ts); a sync
  // queued from a menu stops reading as queued once its job is over. The
  // ledger lives in a ref because it is bookkeeping, not render state.
  const ledger = useRef<JobLedger>(EMPTY_LEDGER);
  const handleSnapshot = useCallback(
    (loaded: readonly Job[] | undefined) => {
      const snapshot = loaded ?? NO_JOBS;
      const diff = diffJobs(ledger.current, snapshot);
      ledger.current = diff.ledger;
      const imports = pendingImports();
      for (const { job, outcome } of diff.transitions) {
        recordFinishedJob(job);
        if (imports.some((item) => item.jobId === job.id)) continue;
        const feedback = describeJobOutcome(job, outcome, t);
        if (feedback.tone === "success") {
          toast.success(feedback.title);
        } else if (feedback.tone === "error") {
          toast.error(feedback.title, { description: feedback.description });
        } else {
          toast.info(feedback.title);
        }
      }
      // A vanished job finished (or was cleaned up) without reporting; its
      // data may still have changed, so refresh as for a reported outcome.
      const changed = diff.transitions.length > 0 || diff.vanished.length > 0;
      if (changed) invalidateAfterJobs(queryClient);
      if (!loaded) return;
      const over = (jobId: string) => isJobOver(jobId, snapshot, diff.ledger, listReceived.current);
      untrackSyncs(pendingSyncs().flatMap((item) => (over(item.jobId) ? [item.jobId] : [])));
      // Retry pending reports on each successful poll, even when no job changed.
      // reportImports serialises attempts and removes only reported imports.
      const settled = imports.flatMap((item): SettledImport[] =>
        over(item.jobId)
          ? [
              {
                ...item,
                jobStatus: snapshot.find((job) => job.id === item.jobId)?.status ?? null
              }
            ]
          : []
      );
      if (settled.length > 0) {
        void reportImports(settled, {
          queryClient,
          t,
          navigate: (href) => router.push(href)
        });
      }
    },
    [queryClient, router, t]
  );
  useEffect(() => {
    handleSnapshot(jobs);
  }, [handleSnapshot, jobs, jobsUpdatedAt]);

  const trackJob = useCallback(
    (job?: Job | Job[]) => {
      const jobs = job === undefined ? [] : Array.isArray(job) ? job : [job];
      if (jobs.length > 0) {
        for (const started of jobs) ledger.current = rememberActiveJob(ledger.current, started);
        // The cached list may already show these jobs finished. Judge it now:
        // a refetch that returns identical data does not re-run the effect.
        handleSnapshot(queryClient.getQueryData<Job[]>(JOBS_KEY));
      }
      fastPollUntil.current = Date.now() + FAST_POLL_WINDOW_MS;
      void queryClient.invalidateQueries({ queryKey: JOBS_KEY });
    },
    [handleSnapshot, queryClient]
  );

  // Upload queue: canonical state in refs (mutated by async callbacks),
  // mirrored into the store the job indicator renders from.
  const uploadsRef = useRef<Map<string, Upload>>(new Map());
  const waitingRef = useRef<string[]>([]);
  const runningRef = useRef<Set<string>>(new Set());
  const [uploadStore] = useState(createUploadStore);
  // Re-renders only when the answer flips, not on every progress tick.
  useBeforeUnloadWarning(
    useSyncExternalStore(
      uploadStore.subscribe,
      () => uploadStore.getSnapshot().some(isUploadPending),
      () => false
    )
  );

  const sync = useCallback(() => {
    uploadStore.set([...uploadsRef.current.values()]);
  }, [uploadStore]);

  const patchUpload = useCallback(
    (id: string, patch: Partial<Upload>) => {
      const upload = uploadsRef.current.get(id);
      if (upload) uploadsRef.current.set(id, { ...upload, ...patch });
      sync();
    },
    [sync]
  );

  const pumpQueue = useCallback(() => {
    const pump = () => {
      while (runningRef.current.size < MAX_UPLOAD_CONNECTIONS && waitingRef.current.length > 0) {
        const id = waitingRef.current.shift();
        const upload = id ? uploadsRef.current.get(id) : undefined;
        if (!id || !upload) continue;

        runningRef.current.add(id);
        patchUpload(id, { status: "uploading" });
        uploadInfoBlob(upload.collectionId, upload.file, (progress) =>
          patchUpload(id, { progress })
        )
          .then((job) => {
            runningRef.current.delete(id);
            uploadsRef.current.delete(id);
            // The bytes are in; the file is searchable only when its job
            // completes, which gets its own toast (job-feedback.ts).
            announce(t("upload_completed_announcement", { name: upload.file.name }));
            toast.info(t("file_uploaded_processing"), { description: upload.file.name });
            trackJob(job);
          })
          .catch((error: unknown) => {
            runningRef.current.delete(id);
            const message = getErrorMessage(error, t);
            patchUpload(id, { status: "failed", errorMessage: message, progress: 0 });
            announce(t("upload_failed_announcement", { name: upload.file.name, message }));
            toast.error(`${t("file_upload_error")}: ${upload.file.name}: ${message}`);
          })
          .finally(() => {
            sync();
            pump();
          });
      }
      sync();
    };
    pump();
  }, [announce, patchUpload, sync, t, trackJob]);

  const queueUploads = useCallback(
    (collectionId: string, files: File[]) => {
      for (const file of files) {
        const id = crypto.randomUUID();
        uploadsRef.current.set(id, {
          id,
          file,
          status: "queued",
          collectionId,
          progress: 0
        });
        waitingRef.current.push(id);
      }
      toast.success(t("uploads_queued", { count: files.length }));
      announce(t("uploads_queued", { count: files.length }));
      pumpQueue();
    },
    [announce, pumpQueue, t]
  );

  const clearFinishedUploads = useCallback(() => {
    for (const [id, upload] of uploadsRef.current) {
      if (upload.status === "completed" || upload.status === "failed") {
        uploadsRef.current.delete(id);
      }
    }
    sync();
  }, [sync]);

  const value = useMemo<JobsContextValue>(
    () => ({ trackJob, queueUploads, clearFinishedUploads, uploadStore, listJobs }),
    [trackJob, queueUploads, clearFinishedUploads, uploadStore, listJobs]
  );

  return <JobsContext.Provider value={value}>{children}</JobsContext.Provider>;
}

export function useJobs(): JobsContextValue {
  const context = useContext(JobsContext);
  if (!context) throw new Error("useJobs must be used inside the (app) layout");
  return context;
}

/**
 * What the job indicator shows: the jobs the backend reports for this user
 * (active and recently finished), the client-side uploads (until the backend
 * job exists), and how many of both run. The provider polls the jobs; this
 * only reads them.
 */
export function useJobActivity(): { jobs: Job[]; uploads: Upload[]; runningCount: number } {
  const { uploadStore, listJobs } = useJobs();
  // The provider's fetcher: the query runs whichever observer's queryFn rendered last.
  const { data: jobs = NO_JOBS } = useQuery({ queryKey: JOBS_KEY, queryFn: listJobs });
  const uploads = useSyncExternalStore(
    uploadStore.subscribe,
    uploadStore.getSnapshot,
    uploadStore.getSnapshot
  );
  const runningCount = jobs.filter(isJobActive).length + uploads.filter(isUploadPending).length;
  return { jobs, uploads, runningCount };
}
