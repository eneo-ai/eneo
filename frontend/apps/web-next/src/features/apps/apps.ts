import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import type { Space } from "@/features/spaces/space";

export type App = Schema<"AppPublic">;
export type AppSparse = Schema<"AppSparse">;
export type AppRun = Schema<"AppRunPublic">;
export type AppRunSparse = Schema<"AppRunSparse">;
export type InputField = Schema<"InputFieldPublic">;
export type InputFieldType = Schema<"InputFieldType">;
export type AppRunStatus = Schema<"Status">;

export type InputFieldRules = {
  /** Mimetype list for the file picker's `accept` attribute (empty = any). */
  acceptString: string;
  /** Max number of files, or Infinity when unset. */
  maxFiles: number;
  /** Max combined size in bytes, or Infinity when unset. */
  maxSize: number;
  /** Per-mimetype size caps (bytes). */
  perTypeLimits: { mimetype: string; sizeLimit: number }[];
};

/** Upload rules for a single input field (port of getExplicitAttachmentRules). */
export function inputFieldRules(
  field: Pick<InputField, "accepted_file_types" | "limit">
): InputFieldRules {
  return {
    acceptString: field.accepted_file_types.map((type) => type.mimetype).join(","),
    maxFiles: field.limit.max_files || Infinity,
    maxSize: field.limit.max_size || Infinity,
    perTypeLimits: field.accepted_file_types.map((type) => ({
      mimetype: type.mimetype,
      sizeLimit: type.size_limit
    }))
  };
}

export const UPLOAD_INPUT_TYPES: InputFieldType[] = [
  "text-upload",
  "audio-upload",
  "image-upload",
  "audio-recorder"
];

/** Apps configured in a space, name-sorted (matching the Svelte SpacesManager). */
export function spaceApps(space: Space): AppSparse[] {
  return [...(space.applications?.apps.items ?? [])].sort((a, b) => a.name.localeCompare(b.name));
}

/** A run is still producing output while queued or in progress. */
export function isRunActive(status: AppRunStatus): boolean {
  return status === "in progress" || status === "queued";
}

/** Title for a run derived from its inputs (text excerpt + file names). */
export function getResultTitle(run: { input: { text: string | null; files: { name: string }[] } }) {
  const parts: string[] = [];
  if (run.input.text) parts.push(`Input: ${run.input.text}`);
  parts.push(...run.input.files.map((file) => file.name));
  return parts.join(", ") || "No input found to generate name";
}

export function appQueryOptions(api: EneoClient, appId: string) {
  return queryOptions({
    queryKey: ["apps", appId],
    queryFn: (): Promise<App> =>
      unwrap(api.GET("/api/v1/apps/{id}/", { params: { path: { id: appId } } }))
  });
}

export function appRunsQueryOptions(api: EneoClient, appId: string) {
  return queryOptions({
    queryKey: ["apps", appId, "runs"],
    queryFn: async (): Promise<AppRunSparse[]> => {
      const page = await unwrap(
        api.GET("/api/v1/apps/{id}/runs/", { params: { path: { id: appId } } })
      );
      return page.items;
    }
  });
}

export function appRunQueryOptions(api: EneoClient, runId: string) {
  return queryOptions({
    queryKey: ["app-runs", runId],
    queryFn: (): Promise<AppRun> =>
      unwrap(api.GET("/api/v1/app-runs/{id}/", { params: { path: { id: runId } } }))
  });
}

/** Short-lived signed URL for downloading or embedding a run's input file. */
export async function fileSignedUrl(
  api: EneoClient,
  fileId: string,
  contentDisposition: "inline" | "attachment" = "attachment"
): Promise<string> {
  const { url } = await unwrap(
    api.POST("/api/v1/files/{id}/signed-url/", {
      params: { path: { id: fileId } },
      body: { content_disposition: contentDisposition }
    })
  );
  return url;
}
