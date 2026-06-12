"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";
import { toast } from "sonner";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError, getErrorMessage, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type Job = Schema<"JobPublic">;

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

/**
 * Query keys that job completion can affect: knowledge lists and counts
 * (uploads, crawls, integration pulls all land as info-blobs) and app runs.
 * Invalidation only refetches mounted queries, so being broad is cheap.
 */
const JOB_INVALIDATION_KEYS = [
  ["spaces"],
  ["collections"],
  ["websites"],
  ["integration-knowledge"],
  ["info-blobs"],
  ["apps"]
];

export function isJobActive(job: Job): boolean {
  return job.status === "in progress" || job.status === "queued";
}

type JobsContextValue = {
  /** Jobs the backend reports for this user (active + recently finished). */
  jobs: Job[];
  /** Client-side upload queue entries (removed once the backend job exists). */
  uploads: Upload[];
  /** Active jobs + active uploads, for the header badge. */
  runningCount: number;
  /** Register a backend job: switches to fast polling for quick feedback. */
  trackJob: () => void;
  /** Queue files for upload into a collection. */
  queueUploads: (collectionId: string, files: File[]) => void;
  clearFinishedUploads: () => void;
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
          code: typeof body?.intric_error_code === "number" ? body.intric_error_code : undefined,
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

export function JobsProvider({ children }: { children: React.ReactNode }) {
  const t = useTranslations();
  const queryClient = useQueryClient();

  const fastPollUntil = useRef(0);

  const { data: jobs = [] } = useQuery({
    queryKey: ["jobs"],
    queryFn: async (): Promise<Job[]> => {
      const page = await unwrap(browserApi.GET("/api/v1/jobs/"));
      return page.items;
    },
    refetchInterval: (query) => {
      // Backend keeps finished jobs visible for a few minutes; only active
      // ones warrant polling. trackJob() restarts a stopped poll.
      if (!query.state.data?.some(isJobActive)) return false;
      return Date.now() < fastPollUntil.current ? FAST_POLL_MS : SLOW_POLL_MS;
    }
  });

  // Detect active → complete transitions (or jobs aging out of the window)
  // and refresh the data they produced.
  const previousJobs = useRef<Map<string, Job>>(new Map());
  useEffect(() => {
    const next = new Map(jobs.map((job) => [job.id, job]));
    const previous = previousJobs.current;
    previousJobs.current = next;

    const completed = [...next.values()].some((job) => {
      const old = previous.get(job.id);
      return old !== undefined && isJobActive(old) && job.status === "complete";
    });
    if (completed || next.size < previous.size) {
      for (const queryKey of JOB_INVALIDATION_KEYS) {
        void queryClient.invalidateQueries({ queryKey });
      }
    }
  }, [jobs, queryClient]);

  const trackJob = useCallback(() => {
    fastPollUntil.current = Date.now() + FAST_POLL_WINDOW_MS;
    void queryClient.invalidateQueries({ queryKey: ["jobs"] });
  }, [queryClient]);

  // Upload queue: canonical state in refs (mutated by async callbacks),
  // mirrored into React state for rendering.
  const uploadsRef = useRef<Map<string, Upload>>(new Map());
  const waitingRef = useRef<string[]>([]);
  const runningRef = useRef<Set<string>>(new Set());
  const [uploads, setUploads] = useState<Upload[]>([]);

  const sync = useCallback(() => {
    setUploads([...uploadsRef.current.values()]);
  }, []);

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
          .then(() => {
            runningRef.current.delete(id);
            uploadsRef.current.delete(id);
            trackJob();
          })
          .catch((error: unknown) => {
            runningRef.current.delete(id);
            const message = getErrorMessage(error, t);
            patchUpload(id, { status: "failed", errorMessage: message, progress: 0 });
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
  }, [patchUpload, sync, t, trackJob]);

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
      pumpQueue();
    },
    [pumpQueue]
  );

  const clearFinishedUploads = useCallback(() => {
    for (const [id, upload] of uploadsRef.current) {
      if (upload.status === "completed" || upload.status === "failed") {
        uploadsRef.current.delete(id);
      }
    }
    sync();
  }, [sync]);

  const runningCount =
    jobs.filter(isJobActive).length +
    uploads.filter((upload) => upload.status === "queued" || upload.status === "uploading").length;

  const value = useMemo<JobsContextValue>(
    () => ({ jobs, uploads, runningCount, trackJob, queueUploads, clearFinishedUploads }),
    [jobs, uploads, runningCount, trackJob, queueUploads, clearFinishedUploads]
  );

  return <JobsContext.Provider value={value}>{children}</JobsContext.Provider>;
}

export function useJobs(): JobsContextValue {
  const context = useContext(JobsContext);
  if (!context) throw new Error("useJobs must be used inside the (app) layout");
  return context;
}
