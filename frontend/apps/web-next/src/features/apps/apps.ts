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

export type ResultTitleLabels = {
  inputPrefix: string;
  empty: string;
};

const DEFAULT_RESULT_TITLE_LABELS: ResultTitleLabels = {
  inputPrefix: "Input",
  empty: "No input found to generate name"
};

/** Title for a run derived from its inputs (text excerpt + file names). */
export function getResultTitle(
  run: { input: { text: string | null; files: { name: string }[] } },
  labels: ResultTitleLabels = DEFAULT_RESULT_TITLE_LABELS
) {
  const parts: string[] = [];
  if (run.input.text) parts.push(`${labels.inputPrefix}: ${run.input.text}`);
  parts.push(...run.input.files.map((file) => file.name));
  return parts.join(", ") || labels.empty;
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
