"use client";

import { useSyncExternalStore } from "react";
import type { Job } from "./jobs";

/**
 * The live feed of the signed-in user's job updates: one EventSource per tab
 * on the app's `/api/jobs/events` proxy, shared by every subscriber. The
 * browser reconnects on its own after a dropped connection; after an HTTP
 * refusal (a session that expired) it stops, and this module tries again
 * later. While the feed is down, JobsProvider's polling carries on, so a
 * missed event only costs a few seconds, never a reload.
 */
export const JOB_EVENTS_PATH = "/api/jobs/events";
export const JOB_EVENT_NAME = "job";
/** How long to wait before reopening a feed the server refused. */
const RETRY_AFTER_REFUSAL_MS = 30_000;

type JobListener = (job: Job) => void;
type Listener = () => void;

let source: EventSource | null = null;
let retryTimer: ReturnType<typeof setTimeout> | null = null;
let connected = false;
/** True once the feed has been open at least once: the next open is a reconnect. */
let wasConnected = false;
const jobListeners = new Set<JobListener>();
const reconnectListeners = new Set<Listener>();
const statusListeners = new Set<Listener>();

function setConnected(next: boolean): void {
  if (connected === next) return;
  connected = next;
  statusListeners.forEach((listener) => listener());
}

function open(): void {
  if (source !== null || typeof EventSource === "undefined") return;
  source = new EventSource(JOB_EVENTS_PATH);
  source.addEventListener("open", () => {
    setConnected(true);
    // Anything that happened while the feed was down is fetched again by
    // whoever subscribed, so the two sides agree.
    if (wasConnected) reconnectListeners.forEach((listener) => listener());
    wasConnected = true;
  });
  source.addEventListener(JOB_EVENT_NAME, (event) => {
    let job: Job;
    try {
      job = JSON.parse((event as MessageEvent<string>).data) as Job;
    } catch {
      return;
    }
    if (typeof job?.id !== "string") return;
    jobListeners.forEach((listener) => listener(job));
  });
  source.addEventListener("error", () => {
    setConnected(false);
    // CLOSED means the server refused (not a blip the browser retries):
    // try again later rather than hammering a dead session.
    if (source?.readyState === EventSource.CLOSED) {
      close();
      if (jobListeners.size > 0 && retryTimer === null) {
        retryTimer = setTimeout(() => {
          retryTimer = null;
          open();
        }, RETRY_AFTER_REFUSAL_MS);
      }
    }
  });
}

function close(): void {
  source?.close();
  source = null;
  setConnected(false);
}

/**
 * Receive every job update for the signed-in user. `onReconnect` fires when
 * the feed comes back after an interruption, so the caller can refetch what
 * it may have missed. Returns the unsubscribe; the feed closes with its last
 * subscriber.
 */
export function subscribeJobEvents(onJob: JobListener, onReconnect?: Listener): () => void {
  jobListeners.add(onJob);
  if (onReconnect) reconnectListeners.add(onReconnect);
  open();
  return () => {
    jobListeners.delete(onJob);
    if (onReconnect) reconnectListeners.delete(onReconnect);
    if (jobListeners.size === 0) {
      if (retryTimer !== null) clearTimeout(retryTimer);
      retryTimer = null;
      close();
      wasConnected = false;
    }
  };
}

const subscribeStatus = (listener: Listener) => {
  statusListeners.add(listener);
  return () => statusListeners.delete(listener);
};
const getConnected = () => connected;
const getServerConnected = () => false;

/** Whether the live feed is open right now; false on the server and while reconnecting. */
export function useJobEventsConnected(): boolean {
  return useSyncExternalStore(subscribeStatus, getConnected, getServerConnected);
}
