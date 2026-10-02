"use client";

import { useAnnounce } from "@astryxdesign/core/hooks";
import { useQuery, useQueryClient } from "@tanstack/react-query";
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
import { browserApi } from "@/lib/api/browser";
import { EneoApiError, getErrorMessage, unwrap } from "@/lib/api/errors";
import { toast } from "@/lib/toast";
import { describeJobOutcome } from "./job-feedback";
import { invalidateAfterJobs } from "./job-invalidation";
import { diffJobs, EMPTY_LEDGER, rememberActiveJob, type JobLedger } from "./job-transitions";
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
   * Pass the job the call returned so its completion is caught even when the
   * first poll already reports it finished (see job-transitions.ts).
   */
  trackJob: (job?: Job) => void;
  /** Queue files for upload into a collection. */
  queueUploads: (collectionId: string, files: File[]) => void;
  clearFinishedUploads: () => void;
  uploadStore: UploadStore;
};

const JobsContext = createContext<JobsContextValue | null>(null);

function uploadInfoBlob(
  collectionId: string,
  file: File,
  onProgress: (progress: number) => void
): Promise<Job> {
  // XMLHttpRequest instead of browserApi: fetch cannot observe upload
  // progress. Same proxy path and error body shapes as openapi-fetch calls.
  return new Promise<Job>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(
      "POST",
      `/api/eneo/api/v1/groups/${encodeURIComponent(collectionId)}/info-blobs/upload/`
    );
    xhr.responseType = "json";
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && event.total > 0) {
        onProgress(Math.floor((event.loaded / event.total) * 100));
      }
    });
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(xhr.response as Job);
        return;
      }
      const body = xhr.response as Record<string, unknown> | null;
      const message =
        (typeof body?.message === "string" && body.message) ||
        (typeof body?.detail === "string" && body.detail) ||
        `Request failed with status ${xhr.status}`;
      reject(
        new EneoApiError(message, {
          status: xhr.status,
          code: typeof body?.eneo_error_code === "number" ? body.eneo_error_code : undefined,
          details: body?.details
        })
      );
    });
    xhr.addEventListener("error", () => reject(new Error("Network error")));
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

  const fastPollUntil = useRef(0);

  const { data: jobs = NO_JOBS } = useQuery({
    queryKey: JOBS_KEY,
    queryFn: fetchJobs,
    // Jobs can be created by another tab or appear after trackJob's first
    // fetch. Keep checking even when the latest response is empty.
    refetchInterval: (query) =>
      Date.now() < fastPollUntil.current || query.state.data?.some(isJobActive)
        ? FAST_POLL_MS
        : SLOW_POLL_MS
  });

  // Each snapshot is compared with the last one: a job that was active and
  // now has an outcome gets a toast, an announcement and a row highlight, and
  // the data it produced is refreshed. The ledger lives in a ref because it
  // is bookkeeping, not render state.
  const ledger = useRef<JobLedger>(EMPTY_LEDGER);
  const handleSnapshot = useCallback(
    (snapshot: readonly Job[]) => {
      const diff = diffJobs(ledger.current, snapshot);
      ledger.current = diff.ledger;
      for (const { job, outcome } of diff.transitions) {
        const feedback = describeJobOutcome(job, outcome, t);
        if (feedback.tone === "success") {
          toast.success(feedback.title);
        } else if (feedback.tone === "error") {
          toast.error(feedback.title, { description: feedback.description });
        } else {
          toast.info(feedback.title);
        }
        announce(feedback.title);
        recordFinishedJob(job);
      }
      // A vanished job finished (or was cleaned up) without reporting; its
      // data may still have changed, so refresh as for a reported outcome.
      if (diff.transitions.length > 0 || diff.vanished.length > 0) {
        invalidateAfterJobs(queryClient);
      }
    },
    [announce, queryClient, t]
  );
  useEffect(() => {
    handleSnapshot(jobs);
  }, [handleSnapshot, jobs]);

  const trackJob = useCallback(
    (job?: Job) => {
      if (job) {
        ledger.current = rememberActiveJob(ledger.current, job);
        // The cached list may already show this job finished. Judge it now:
        // a refetch that returns identical data does not re-run the effect.
        handleSnapshot(queryClient.getQueryData<Job[]>(JOBS_KEY) ?? NO_JOBS);
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
    () => ({ trackJob, queueUploads, clearFinishedUploads, uploadStore }),
    [trackJob, queueUploads, clearFinishedUploads, uploadStore]
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
  const { uploadStore } = useJobs();
  const { data: jobs = NO_JOBS } = useQuery({ queryKey: JOBS_KEY, queryFn: fetchJobs });
  const uploads = useSyncExternalStore(
    uploadStore.subscribe,
    uploadStore.getSnapshot,
    uploadStore.getSnapshot
  );
  const runningCount =
    jobs.filter(isJobActive).length +
    uploads.filter((upload) => upload.status === "queued" || upload.status === "uploading").length;
  return { jobs, uploads, runningCount };
}
