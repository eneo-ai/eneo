import { browser } from "$app/environment";
import { invalidate } from "$app/navigation";
import { createContext } from "$lib/core/context";
import type { Intric, Job } from "@intric/intric-js";
import { derived, writable } from "svelte/store";

import { m } from "$lib/paraglide/messages";
export { getJobManager, initJobManager, jobCompletionEvents };

// Global store for job completion events (can be subscribed to from any component)
const jobCompletionEvents = writable<{ timestamp: number; jobId: string } | null>(null);

const [getJobManager, setJobManager] =
  createContext<ReturnType<typeof createJobManager>>("Handles jobs");

function initJobManager(data: { intric: Intric }) {
  setJobManager(createJobManager(data));
}

function createJobManager(data: { intric: Intric }) {
  const { intric } = data;

  // Panel -------------------------------------------------------------------  //
  const showJobManagerPanel = writable(false);

  // Backend jobs -------------------------------------------------------------------  //

  let currentJobs: Map<string, Job> = new Map();
  const currentJobStore = writable<Job[]>([]);

  function addJob(job: Job) {
    currentJobs.set(job.id, job);
    currentJobStore.set([...currentJobs.values()]);
    startUpdatePolling();
  }

  // Keep track of how many times getting jobs has failed
  let jobUpdateErrors = 0;
  /** Will get all currently running jobs from the server */
  async function updateJobs(): Promise<Job[]> {
    let jobs: Job[] = [];
    try {
      jobs = await intric.jobs.list();
      // Reset errors on success
      jobUpdateErrors = 0;
    } catch (error) {
      console.error("JobManager: Could not get jobs from server", error);
      jobUpdateErrors += 1;
      // Returning an empyt array will cancel the job update Interval/update polling
      // This timeout starts if after 20 seconds if we do not have 5 consecutive errors
      if (jobUpdateErrors < 5) {
        setTimeout(() => {
          startUpdatePolling();
        }, 20 * 1000);
      }
      return [];
    }
    const updatedJobs = new Map(
      // Keep failed and completed jobs so we can show their status in the UI
      // Backend returns completed jobs for 5 minutes to allow UI to detect completion
      jobs
        .filter((job) => job.status === "in progress" || job.status === "queued" || job.status === "failed" || job.status === "complete")
        .map((job) => [job.id, job])
    );

    // Detect if any jobs changed from active to complete
    let jobsCompleted = false;
    for (const [id, newJob] of updatedJobs) {
      const oldJob = currentJobs.get(id);
      if (oldJob &&
          (oldJob.status === "in progress" || oldJob.status === "queued") &&
          newJob.status === "complete") {
        jobsCompleted = true;
        break;
      }
    }

    // Also check if jobs were removed (size decreased)
    const jobsRemoved = updatedJobs.size < currentJobs.size;

    if (jobsCompleted || jobsRemoved) {
      // Some jobs have finished: refresh related data
      if (browser) {
        // Invalidate data dependencies to trigger SvelteKit page data refresh
        invalidate("blobs:list");
        // Emit job completion event that components can subscribe to
        jobCompletionEvents.set({ timestamp: Date.now(), jobId: "any" });
      }
    }
    currentJobs = updatedJobs;
    currentJobStore.set([...currentJobs.values()]);
    return jobs;
  }

  const updateJobsFrequency_ms = 30 * 1000;
  const updateJobsFrequency_fast_ms = 2 * 1000; // Check every 2 seconds for faster feedback
  const fastPollDuration_ms = 15 * 1000; // Use fast polling for 15 seconds after job starts
  let updateJobsInterval: ReturnType<typeof setInterval>;
  let updateJobsRunning = false;
  let lastJobAddedTime = 0;

  async function startUpdatePolling() {
    if (updateJobsRunning === false) {
      updateJobsRunning = true;
      await updateJobs();
      updateJobsInterval = setInterval(async () => {
        const jobs = await updateJobs();
        const hasActiveJobs = jobs.some((job) => job.status === "in progress" || job.status === "queued");
        if (!hasActiveJobs) {
          stopUpdatePolling();
        }
      }, updateJobsFrequency_ms);
    }
  }

  async function startFastUpdatePolling() {
    // Use fast polling for recently added jobs
    // Stop any existing polling to allow fast polling to take over
    if (updateJobsRunning) {
      clearInterval(updateJobsInterval);
    }

    updateJobsRunning = true;
    lastJobAddedTime = Date.now();
    await updateJobs();

    updateJobsInterval = setInterval(async () => {
      const jobs = await updateJobs();
      const hasActiveJobs = jobs.some((job) => job.status === "in progress" || job.status === "queued");
      const timeSinceJobAdded = Date.now() - lastJobAddedTime;

      // Switch to slow polling after 15 seconds or if no active jobs
      if (!hasActiveJobs || timeSinceJobAdded > fastPollDuration_ms) {
        if (!hasActiveJobs) {
          stopUpdatePolling();
        } else {
          // Switch to slow polling
          clearInterval(updateJobsInterval);
          updateJobsInterval = setInterval(async () => {
            const jobs = await updateJobs();
            const hasActiveJobs = jobs.some((job) => job.status === "in progress" || job.status === "queued");
            if (!hasActiveJobs) {
              stopUpdatePolling();
            }
          }, updateJobsFrequency_ms);
        }
      }
    }, updateJobsFrequency_fast_ms);
  }

  // Entry point
  if (browser) {
    startUpdatePolling();
  }

  function stopUpdatePolling() {
    updateJobsRunning = false;
    clearInterval(updateJobsInterval);
  }

  // Uploading -------------------------------------------------------------------  //

  type Upload = {
    id: string;
    file: File;
    status: "queued" | "uploading" | "completed" | "failed";
    /// Destination for this file
    groupId: string;
    progress: number;
    errorMessage?: string;
  };

  const currentUploads: Map<string, Upload> = new Map();
  const currentUploadsStore = writable<Upload[]>([]);

  const waitingUploads: Set<string> = new Set();
  const runningUploads: Set<string> = new Set();
  const max_upload_connections = 5;

  function queueUploads(groupId: string, files: File[]) {
    files.forEach((file) => {
      const id = crypto.randomUUID();
      currentUploads.set(id, {
        id,
        file,
        status: "queued",
        progress: 0,
        groupId,
        errorMessage: undefined
      });
      waitingUploads.add(id);
    });

    continueUploadQueue();
  }

  function continueUploadQueue() {
    startSyncingUploads();
    while (runningUploads.size < max_upload_connections && waitingUploads.size > 0) {
      const uploadId = waitingUploads.values().next().value;
      if (!uploadId) break;
      waitingUploads.delete(uploadId);
      const upload = currentUploads.get(uploadId);
      if (upload) {
        runningUploads.add(uploadId);
        upload.status = "uploading";
        intric.infoBlobs
          .upload({
            group_id: upload.groupId,
            file: upload.file,
            onProgress: (ev) => {
              if (ev.total > 0) {
                upload.progress = Math.floor((ev.loaded / ev.total) * 100);
              }
            }
          })
          .then((job) => {
            // Delete from running uploads
            runningUploads.delete(uploadId);
            upload.status = "completed";
            upload.errorMessage = undefined;
            addJob(job);
            // Delete from upload list
            // This does not directly update the store, but next time the store is updated this upload will no longer be included
            currentUploads.delete(upload.id);
            continueUploadQueue();
          })
          .catch((error) => {
            const fallbackMessage = m.file_upload_error();
            const message =
              error instanceof Error && error.message
                ? error.message
                : fallbackMessage;
            alert(`${fallbackMessage}: ${upload.file.name}\n${message}`);
            runningUploads.delete(uploadId);
            upload.status = "failed";
            upload.errorMessage = message;
            upload.progress = 0;
            currentUploads.set(upload.id, upload);
            console.error("Upload error:", error);
            continueUploadQueue();
          })
          .finally(() => {
            currentUploadsStore.set([...currentUploads.values()]);
          });
      }
    }
    currentUploadsStore.set([...currentUploads.values()]);
  }

  const uploadSyncFrequency_ms = 1000;
  let syncUploadsInterval: ReturnType<typeof setInterval>;
  let syncUploadsRunning = false;
  function startSyncingUploads() {
    if (syncUploadsRunning === false) {
      syncUploadsRunning = true;
      currentUploadsStore.set([...currentUploads.values()]);
      syncUploadsInterval = setInterval(async () => {
        currentUploadsStore.set([...currentUploads.values()]);
        if (runningUploads.size === 0 && waitingUploads.size === 0) {
          stopSyncingUploads();
        }
      }, uploadSyncFrequency_ms);
    }
  }

  function stopSyncingUploads() {
    syncUploadsRunning = false;
    clearInterval(syncUploadsInterval);
  }

  function clearFinishedUploads() {
    for (const [id, upload] of currentUploads.entries()) {
      if (upload.status === "completed" || upload.status === "failed") {
        currentUploads.delete(id);
      }
    }
    currentUploadsStore.set([...currentUploads.values()]);
  }

  const currentlyRunningJobs = derived(
    [currentJobStore, currentUploadsStore],
    ([jobs, uploads]) => {
      const activeJobs = jobs.filter((job) => job.status === "in progress" || job.status === "queued");
      const activeUploads = uploads.filter((upload) =>
        upload.status === "queued" || upload.status === "uploading"
      );
      return activeJobs.length + activeUploads.length;
    }
  );

  return {
    state: {
      jobs: { subscribe: currentJobStore.subscribe },
      uploads: { subscribe: currentUploadsStore.subscribe },
      currentlyRunningJobs,
      showJobManagerPanel
    },
    addJob,
    queueUploads,
    clearFinishedUploads,
    updateJobs,
    startUpdatePolling,
    startFastUpdatePolling
  };
}
