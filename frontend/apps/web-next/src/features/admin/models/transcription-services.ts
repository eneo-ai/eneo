import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { EneoApiError, getErrorMessage, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

/**
 * The organisation's services for word timings and speaker identification
 * (such as Vemsa). The API key is write-only: no response carries it, and
 * nothing here keeps one after it was sent.
 */
export type TranscriptionService = Schema<"TranscriptionServicePublic">;
export type TranscriptionServiceCreate = Schema<"TranscriptionServiceCreate">;
export type TranscriptionServiceUpdate = Schema<"TranscriptionServiceUpdate">;
export type TranscriptionServiceLastCheck = Schema<"TranscriptionServiceLastCheckPublic">;
export type TranscriptionServiceSummary = Schema<"TranscriptionServiceSummary">;

// An organisation connects at most 200 services (the backend's limit, one
// page), so a single page holds them all.
const ALL = { limit: 200 };

export const TRANSCRIPTION_SERVICES_KEY = ["admin-transcription-services"];

/** The administrator's list, with addresses and each service's latest check. */
export function transcriptionServicesQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: TRANSCRIPTION_SERVICES_KEY,
    queryFn: async (): Promise<TranscriptionService[]> =>
      (await unwrap(api.GET("/api/v1/admin/transcription-services/", { params: { query: ALL } })))
        .items
  });
}

export const TRANSCRIPTION_SERVICE_CATALOGUE_KEY = ["transcription-service-catalogue"];

/** The services by name, without addresses or keys, for granting them to spaces. */
export function transcriptionServiceCatalogueQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: TRANSCRIPTION_SERVICE_CATALOGUE_KEY,
    queryFn: async (): Promise<TranscriptionServiceSummary[]> =>
      (await unwrap(api.GET("/api/v1/transcription-services/", { params: { query: ALL } }))).items
  });
}

export function createTranscriptionService(api: EneoClient, body: TranscriptionServiceCreate) {
  return unwrap(api.POST("/api/v1/admin/transcription-services/", { body }));
}

/** Only the fields sent change; a new endpoint needs a new `api_key` in the same request. */
export function updateTranscriptionService(
  api: EneoClient,
  id: string,
  body: TranscriptionServiceUpdate
) {
  return unwrap(
    api.PATCH("/api/v1/admin/transcription-services/{connection_id}/", {
      params: { path: { connection_id: id } },
      body
    })
  );
}

/** Removes the service and its space grants. */
export function deleteTranscriptionService(api: EneoClient, id: string) {
  return unwrap(
    api.DELETE("/api/v1/admin/transcription-services/{connection_id}/", {
      params: { path: { connection_id: id } }
    })
  );
}

/** Asks the service whether it would take a job with the saved settings; sends no audio. */
export function checkTranscriptionService(api: EneoClient, id: string) {
  return unwrap(
    api.POST("/api/v1/admin/transcription-services/{connection_id}/check/", {
      params: { path: { connection_id: id } }
    })
  );
}

/**
 * The backend stores an address without its trailing "/" or "/v1", so
 * https://x/ and https://x/v1 are the saved https://x, not a move.
 */
export function endpointBase(url: string): string {
  const base = url.trim().replace(/\/+$/, "");
  return base.endsWith("/v1") ? base.slice(0, -3).replace(/\/+$/, "") : base;
}

// The backend names why an address is refused with a closed code.
const ENDPOINT_PROBLEMS: Record<string, string> = {
  service_endpoint_too_long: "speaker_service_endpoint_too_long",
  service_endpoint_not_http: "speaker_service_endpoint_not_http",
  service_endpoint_credentials: "speaker_service_endpoint_credentials",
  service_endpoint_query: "speaker_service_endpoint_query",
  service_endpoint_port: "speaker_service_endpoint_port"
};

type ValidationEntry = { location?: unknown; type?: unknown };

function validationEntries(error: EneoApiError): ValidationEntry[] {
  const errors = (error.details as { errors?: unknown } | undefined)?.errors;
  return Array.isArray(errors) ? (errors as ValidationEntry[]) : [];
}

/**
 * Why the backend refused the address, in the user's language, when the
 * refusal (422) is about the address; null when it is about something else.
 */
export function endpointProblem(error: unknown, t: (key: string) => string): string | null {
  if (!(error instanceof EneoApiError) || error.status !== 422) return null;
  const entries = validationEntries(error).filter(
    (entry) => Array.isArray(entry.location) && entry.location.includes("endpoint_url")
  );
  if (entries.length === 0) return null;
  const key = entries
    .map((entry) => (typeof entry.type === "string" ? ENDPOINT_PROBLEMS[entry.type] : undefined))
    .find((found) => found !== undefined);
  return key ? t(key) : getErrorMessage(error, t);
}

/** The name is taken by another of the organisation's services. */
export function isServiceNameTaken(error: unknown): boolean {
  return error instanceof EneoApiError && error.status === 409;
}

/** Changes a service still in the list; one that has left it stays gone. */
export function patchService(
  list: TranscriptionService[] | undefined,
  id: string,
  fields: Partial<TranscriptionService>
): TranscriptionService[] | undefined {
  if (!list?.some((service) => service.id === id)) return list;
  return list.map((service) => (service.id === id ? { ...service, ...fields } : service));
}

/**
 * Applies a saved service as the server returned it, its check included: the
 * server clears a check whose address or key changed, by anyone. The default
 * mark belongs to the organisation, not to the row: only the answer to a save
 * that changed it (`marksDefault`) brings it, and takes it from the service
 * that had it. A slower answer to another edit carries the mark as it was when
 * that edit was sent, so it keeps what the list shows.
 */
export function applySavedService(
  list: TranscriptionService[] | undefined,
  next: TranscriptionService,
  marksDefault: boolean
): TranscriptionService[] | undefined {
  const current = list?.find((service) => service.id === next.id);
  if (!list || !current) return list;
  return list.map((service) => {
    if (service.id === next.id) {
      return marksDefault ? next : { ...next, is_default: current.is_default };
    }
    return marksDefault && next.is_default && service.is_default
      ? { ...service, is_default: false }
      : service;
  });
}
