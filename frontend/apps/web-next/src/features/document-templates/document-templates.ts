import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { EneoApiError, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type DocumentTemplate = Schema<"DocumentTemplatePublic">;
export const DOCUMENT_TEMPLATES_KEY = ["document-templates"] as const;

export function documentTemplatesQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: DOCUMENT_TEMPLATES_KEY,
    queryFn: async ({ signal }): Promise<Schema<"DocumentTemplateList"> | null> => {
      try {
        return await unwrap(api.GET("/api/v1/document-templates/", { signal }));
      } catch (error) {
        if (error instanceof EneoApiError && error.status === 404) return null;
        throw error;
      }
    },
    retry: false
  });
}

export function uploadDocumentTemplate(
  api: EneoClient,
  file: File,
  name: string,
  isDefault: boolean
) {
  const body = new FormData();
  body.append("file", file);
  body.append("name", name);
  body.append("is_default", String(isDefault));
  return unwrap(
    api.POST("/api/v1/document-templates/", {
      // OpenAPI represents multipart binary fields as strings; the wire body remains FormData.
      body: body as unknown as Schema<"Body_upload_document_template_api_v1_document_templates__post">,
      bodySerializer: () => body
    })
  );
}

export function updateDocumentTemplate(
  api: EneoClient,
  id: string,
  update: Schema<"DocumentTemplateUpdate">
) {
  return unwrap(
    api.PATCH("/api/v1/document-templates/{id}/", {
      params: { path: { id } },
      body: update
    })
  );
}

export function replaceDocumentTemplate(api: EneoClient, id: string, file: File) {
  const body = new FormData();
  body.append("file", file);
  return unwrap(
    api.PUT("/api/v1/document-templates/{id}/content/", {
      params: { path: { id } },
      // OpenAPI represents multipart binary fields as strings; the wire body remains FormData.
      body: body as unknown as Schema<"Body_replace_document_template_content_api_v1_document_templates__id__content__put">,
      bodySerializer: () => body
    })
  );
}

export function deleteDocumentTemplate(api: EneoClient, id: string) {
  return unwrap(api.DELETE("/api/v1/document-templates/{id}/", { params: { path: { id } } }));
}

export function downloadDocumentTemplate(api: EneoClient, id: string) {
  return unwrap(
    api.GET("/api/v1/document-templates/{id}/content/", {
      params: { path: { id } },
      parseAs: "blob"
    })
  );
}

export function downloadBuiltinDocumentTemplate(api: EneoClient, language: "sv" | "en") {
  return unwrap(
    api.GET("/api/v1/document-templates/builtin/", {
      params: { query: { language } },
      parseAs: "blob"
    })
  );
}
