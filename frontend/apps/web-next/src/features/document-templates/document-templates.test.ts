import { QueryClient } from "@tanstack/react-query";
import createClient from "openapi-fetch";
import { expect, it, vi } from "vitest";
import type { paths } from "@/lib/api/schema";
import {
  documentTemplatesQueryOptions,
  uploadDocumentTemplate,
  replaceDocumentTemplate,
  updateDocumentTemplate,
  deleteDocumentTemplate,
  downloadDocumentTemplate,
  downloadBuiltinDocumentTemplate
} from "./document-templates";

it("loads the saved template library and its runtime availability through the typed API", async () => {
  const result = { items: [], runtime_configured: false };
  const fetch = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(result), {
      status: 200,
      headers: { "content-type": "application/json" }
    })
  );
  const api = createClient<paths>({ baseUrl: "http://localhost", fetch });
  const client = new QueryClient();
  expect(await client.query(documentTemplatesQueryOptions(api))).toEqual(result);
  expect(new URL((fetch.mock.calls[0]![0] as Request).url).pathname).toBe(
    "/api/v1/document-templates/"
  );
});

it("keeps replacement multipart content separate from identity metadata and encodes saved-object actions", async () => {
  const fetch = vi
    .fn()
    .mockImplementation(() =>
      Promise.resolve(
        new Response("{}", { status: 200, headers: { "content-type": "application/json" } })
      )
    );
  const api = createClient<paths>({ baseUrl: "http://localhost", fetch });
  await replaceDocumentTemplate(
    api,
    "template-1",
    new File(["replacement bytes"], "replacement.docx")
  );
  const replacement = fetch.mock.calls[0]![0] as Request;
  expect(replacement.method).toBe("PUT");
  expect(new URL(replacement.url).pathname).toBe("/api/v1/document-templates/template-1/content/");
  const multipart = await replacement.formData();
  expect([...multipart.keys()]).toEqual(["file"]);
  expect(await (multipart.get("file") as File).text()).toBe("replacement bytes");
  await updateDocumentTemplate(api, "template-1", { is_default: true });
  const update = fetch.mock.calls[1]![0] as Request;
  expect(update.method).toBe("PATCH");
  expect(await update.json()).toEqual({ is_default: true });
  await deleteDocumentTemplate(api, "template-1");
  const deletion = fetch.mock.calls[2]![0] as Request;
  expect(deletion.method).toBe("DELETE");
  expect(new URL(deletion.url).pathname).toBe("/api/v1/document-templates/template-1/");
});

it("returns downloaded bytes and retains structured backend errors for blob requests", async () => {
  const fetch = vi.fn().mockImplementation(() =>
    Promise.resolve(
      new Response("word bytes", {
        status: 200,
        headers: {
          "content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        }
      })
    )
  );
  const api = createClient<paths>({ baseUrl: "http://localhost", fetch });
  expect(await (await downloadDocumentTemplate(api, "saved")).text()).toBe("word bytes");
  for (const language of ["sv", "en"] as const) {
    expect(await (await downloadBuiltinDocumentTemplate(api, language)).text()).toBe("word bytes");
    expect(new URL((fetch.mock.lastCall![0] as Request).url).searchParams.get("language")).toBe(
      language
    );
  }
  fetch.mockImplementation(() =>
    Promise.resolve(
      new Response(JSON.stringify({ message: "Runtime unavailable", error_id: "template-error" }), {
        status: 503,
        headers: { "content-type": "application/json", "x-trace-id": "template-trace" }
      })
    )
  );
  await expect(downloadBuiltinDocumentTemplate(api, "sv")).rejects.toMatchObject({
    status: 503,
    message: "Runtime unavailable",
    errorId: "template-error",
    traceId: "template-trace"
  });
});

it("treats only a list404 as an older unsupported backend", async () => {
  const fetch = vi.fn().mockImplementation(() =>
    Promise.resolve(
      new Response(JSON.stringify({ message: "Unavailable" }), {
        status: 404,
        headers: { "content-type": "application/json" }
      })
    )
  );
  const api = createClient<paths>({ baseUrl: "http://localhost", fetch });
  expect(await new QueryClient().query(documentTemplatesQueryOptions(api))).toBeNull();
  fetch.mockImplementation(() =>
    Promise.resolve(
      new Response(JSON.stringify({ message: "Unavailable" }), {
        status: 503,
        headers: { "content-type": "application/json" }
      })
    )
  );
  await expect(new QueryClient().query(documentTemplatesQueryOptions(api))).rejects.toMatchObject({
    status: 503
  });
});

it("sends actual multipart file bytes and metadata with the browser-owned boundary", async () => {
  const fetch = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ id: "saved" }), {
      status: 201,
      headers: { "content-type": "application/json" }
    })
  );
  const api = createClient<paths>({ baseUrl: "http://localhost", fetch });
  const file = new File(["word bytes"], "report.docx");
  await uploadDocumentTemplate(api, file, "Report", false);
  const request = fetch.mock.calls[0]![0] as Request;
  expect(request.method).toBe("POST");
  expect(new URL(request.url).pathname).toBe("/api/v1/document-templates/");
  expect(request.headers.get("content-type")).toContain("multipart/form-data; boundary=");
  const body = await request.formData();
  expect(await (body.get("file") as File).text()).toBe("word bytes");
  expect(body.get("name")).toBe("Report");
  expect(body.get("is_default")).toBe("false");
});
