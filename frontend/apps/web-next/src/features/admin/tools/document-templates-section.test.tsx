// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  DOCUMENT_TEMPLATES_KEY,
  type DocumentTemplate
} from "@/features/document-templates/document-templates";
import { expectNoAxeViolations } from "@/test/axe";

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const patch = vi.hoisted(() => vi.fn());
const put = vi.hoisted(() => vi.fn());
const remove = vi.hoisted(() => vi.fn());
const saveBlob = vi.hoisted(() => vi.fn());
vi.mock("@/features/files/signed-file-url", () => ({ saveBlob }));
vi.mock("@/lib/api/browser", () => ({
  browserApi: { GET: get, POST: post, PATCH: patch, PUT: put, DELETE: remove }
}));
vi.mock("use-intl", () => ({ useTranslations: () => (key: string) => key, useLocale: () => "en" }));
import { DocumentTemplatesSection } from "./document-templates-section";

const template: DocumentTemplate = {
  id: "template-1",
  name: "Municipal report",
  filename: "report.docx",
  sha256: "digest",
  size_bytes: 2048,
  syntax: "braces",
  status: "ready",
  is_default: true,
  selected_by: 2,
  created_at: "2026-10-01T12:00:00Z",
  updated_at: "2026-10-01T12:00:00Z",
  checks: { heading_styles: { ok: false, detail: "Heading 2 is missing" } },
  placeholders: [
    {
      name: "case_number",
      syntax: "braces",
      kind: "text",
      location: "body",
      supported: true,
      label: "Case number",
      hint: "The municipality's case number"
    }
  ]
};
const ok = (data: unknown) =>
  Promise.resolve({ data, response: new Response("{}", { status: 200 }) });
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
beforeEach(() => {
  get.mockReset();
  post.mockReset();
  patch.mockReset();
  put.mockReset();
  remove.mockReset();
});

it("replaces the captured template's bytes and retains the selected file after failure", async () => {
  get.mockImplementation(() => ok({ items: [template], runtime_configured: true }));
  put.mockResolvedValueOnce({
    error: { message: "Cannot store file" },
    response: new Response("{}", { status: 503 })
  });
  put.mockImplementation(() => ok({ ...template, filename: "replacement.docx" }));
  const client = show();
  fireEvent.click(await screen.findByRole("button", { name: "actions: Municipal report" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "document_template_replace_file" }));
  const dialog = screen.getByRole("dialog", { name: "document_template_replace_file" });
  act(() =>
    client.setQueryData(DOCUMENT_TEMPLATES_KEY, {
      items: [{ ...template, id: "other", name: "Another report" }],
      runtime_configured: true
    })
  );
  const file = new File(["new bytes"], "replacement.docx");
  fireEvent.change(dialog.querySelector('input[type="file"]')!, { target: { files: [file] } });
  fireEvent.click(within(dialog).getByRole("button", { name: "document_template_save" }));
  expect(await within(dialog).findByText("Cannot store file")).toBeTruthy();
  expect(within(dialog).getByText("replacement.docx")).toBeTruthy();
  fireEvent.click(within(dialog).getByRole("button", { name: "document_template_save" }));
  await waitFor(() => expect(put).toHaveBeenCalledTimes(2));
  for (const call of put.mock.calls) {
    expect(call[0]).toBe("/api/v1/document-templates/{id}/content/");
    expect(call[1].params.path.id).toBe(template.id);
    expect((call[1].body as FormData).get("file")).toMatchObject({
      name: file.name,
      size: file.size
    });
    expect([...call[1].body.keys()]).toEqual(["file"]);
  }
  expect(patch).not.toHaveBeenCalled();
  await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
});

it("makes a template default only after a successful save and refreshes the list", async () => {
  let items = [{ ...template, is_default: false }];
  get.mockImplementation(() => ok({ items, runtime_configured: true }));
  patch.mockResolvedValueOnce({
    error: { message: "Default rejected" },
    response: new Response("{}", { status: 503 })
  });
  patch.mockImplementation(() => {
    items = [template];
    return ok(template);
  });
  const client = show();
  fireEvent.click(await screen.findByRole("button", { name: "actions: Municipal report" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "document_template_make_default" }));
  expect(await screen.findByText("Default rejected")).toBeTruthy();
  expect(get).toHaveBeenCalledTimes(1);
  act(() =>
    client.setQueryData(DOCUMENT_TEMPLATES_KEY, {
      items: [{ ...template, id: "other", name: "Another report", is_default: false }],
      runtime_configured: true
    })
  );
  fireEvent.click(screen.getByRole("button", { name: "retry" }));
  await waitFor(() => expect(patch).toHaveBeenCalledTimes(2));
  for (const call of patch.mock.calls)
    expect(call).toEqual([
      "/api/v1/document-templates/{id}/",
      { params: { path: { id: template.id } }, body: { is_default: true } }
    ]);
  await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
  const row = screen.getByText("Municipal report").closest("li")!;
  expect(within(row).getByText("document_template_default")).toBeTruthy();
});

it("confirms the captured delete target, blocks duplicate presses and restores list focus", async () => {
  let items = [template];
  get.mockImplementation(() => ok({ items, runtime_configured: true }));
  let finish!: (value: unknown) => void;
  remove.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      })
  );
  remove.mockImplementation(() => {
    items = [];
    return ok(undefined);
  });
  const client = show();
  client.setQueryData(["assistants", "bound-assistant"], {
    document_template: { mode: "selected", template_id: template.id }
  });
  client.setQueryData([...DOCUMENT_TEMPLATES_KEY, "available"], {
    items: [{ id: template.id, name: template.name, is_default: true }]
  });
  fireEvent.click(await screen.findByRole("button", { name: "actions: Municipal report" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "document_template_delete" }));
  const dialog = screen.getByRole("alertdialog");
  expect(within(dialog).getByText("Municipal report")).toBeTruthy();
  act(() =>
    client.setQueryData(DOCUMENT_TEMPLATES_KEY, {
      items: [{ ...template, id: "other", name: "Another report" }],
      runtime_configured: true
    })
  );
  const confirm = within(dialog).getByRole("button", { name: "document_template_delete" });
  confirm.focus();
  fireEvent.click(confirm);
  await waitFor(() => expect(confirm.getAttribute("aria-busy")).toBe("true"));
  fireEvent.click(confirm);
  expect(remove).toHaveBeenCalledTimes(1);
  finish({ error: { message: "Delete rejected" }, response: new Response("{}", { status: 503 }) });
  expect(await within(dialog).findByText("Delete rejected")).toBeTruthy();
  fireEvent.click(confirm);
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  expect(client.getQueryState(["assistants", "bound-assistant"])?.isInvalidated).toBe(true);
  expect(client.getQueryState([...DOCUMENT_TEMPLATES_KEY, "available"])?.isInvalidated).toBe(true);
  for (const call of remove.mock.calls)
    expect(call).toEqual([
      "/api/v1/document-templates/{id}/",
      { params: { path: { id: template.id } } }
    ]);
  await waitFor(() =>
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "document_templates" }))
  );
});

it("downloads stored bytes with the captured filename and limits the built-in download to configured runtimes", async () => {
  const bytes = new Blob(["stored document"]);
  get.mockImplementation((path: string) =>
    path.endsWith("/content/") ? ok(bytes) : ok({ items: [template], runtime_configured: false })
  );
  const client = show();
  const builtin = await screen.findByRole("button", { name: "document_template_download_builtin" });
  expect((builtin as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText("document_template_builtin_unavailable")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "actions: Municipal report" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "document_template_download" }));
  await waitFor(() => expect(saveBlob).toHaveBeenCalledWith(bytes, "report.docx"));
  expect(get).toHaveBeenCalledWith("/api/v1/document-templates/{id}/content/", {
    params: { path: { id: template.id } },
    parseAs: "blob"
  });
  act(() =>
    client.setQueryData(DOCUMENT_TEMPLATES_KEY, { items: [template], runtime_configured: true })
  );
  get.mockImplementation(() => ok(bytes));
  await waitFor(() => expect((builtin as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(builtin);
  await waitFor(() =>
    expect(get).toHaveBeenCalledWith("/api/v1/document-templates/builtin/", {
      params: { query: { language: "en" } },
      parseAs: "blob"
    })
  );
  expect(saveBlob).toHaveBeenLastCalledWith(bytes, "eneo-template-en.docx");
});

it("retries a failed stored download with its reviewed identity and filename after a list refresh", async () => {
  const bytes = new Blob(["stored bytes"]);
  let attempts = 0;
  let finish!: (value: unknown) => void;
  get.mockImplementation((path: string) => {
    if (!path.endsWith("/content/")) return ok({ items: [template], runtime_configured: true });
    if (++attempts === 1)
      return Promise.resolve({
        error: { message: "Download offline" },
        response: new Response("{}", { status: 503 })
      });
    return new Promise((resolve) => {
      finish = resolve;
    });
  });
  const client = show();
  fireEvent.click(await screen.findByRole("button", { name: "actions: Municipal report" }));
  // The menu moves focus into itself on the next frame; let it, as a user would.
  await act(() => new Promise((resolve) => requestAnimationFrame(resolve)));
  fireEvent.click(screen.getByRole("menuitem", { name: "document_template_download" }));
  expect(await screen.findByText("Download offline")).toBeTruthy();
  act(() =>
    client.setQueryData(DOCUMENT_TEMPLATES_KEY, {
      items: [{ ...template, id: "other", name: "Another report", filename: "other.docx" }],
      runtime_configured: true
    })
  );
  const retry = screen.getByRole("button", { name: "retry" });
  retry.focus();
  fireEvent.click(retry);
  await waitFor(() => expect(retry.getAttribute("aria-busy")).toBe("true"));
  expect(document.activeElement).toBe(retry);
  expect(retry.isConnected).toBe(true);
  fireEvent.click(retry);
  expect(attempts).toBe(2);
  finish(await ok(bytes));
  await waitFor(() => expect(saveBlob).toHaveBeenCalledWith(bytes, template.filename));
  await waitFor(() =>
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "document_templates" }))
  );
  for (const call of get.mock.calls.filter(([path]) => path.endsWith("/content/")))
    expect(call[1].params.path.id).toBe(template.id);
});

it("keeps the built-in download button focused and blocks a second request while pending", async () => {
  let finish!: (value: unknown) => void;
  get.mockImplementation((path: string) =>
    path.endsWith("/builtin/")
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : ok({ items: [], runtime_configured: true })
  );
  show();
  const button = await screen.findByRole("button", { name: "document_template_download_builtin" });
  button.focus();
  fireEvent.click(button);
  await waitFor(() => expect(button.getAttribute("aria-busy")).toBe("true"));
  expect((button as HTMLButtonElement).disabled).toBe(false);
  expect(document.activeElement).toBe(button);
  fireEvent.click(button);
  expect(get.mock.calls.filter(([path]) => path.endsWith("/builtin/"))).toHaveLength(1);
  finish(await ok(new Blob(["built-in bytes"])));
  await waitFor(() => expect(button.getAttribute("aria-busy")).not.toBe("true"));
});

it("exposes the library, checks, menu and upload fields without axe violations", async () => {
  get.mockImplementation(() => ok({ items: [template], runtime_configured: false }));
  show();
  fireEvent.click(await screen.findByRole("button", { name: "document_template_show_checks" }));
  await screen.findByText("Heading 2 is missing");
  await expectNoAxeViolations(document.body);
  fireEvent.click(screen.getByRole("button", { name: "actions: Municipal report" }));
  await expectNoAxeViolations(document.body);
  fireEvent.click(screen.getByRole("menuitem", { name: "document_template_rename" }));
  await expectNoAxeViolations(document.body);
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "cancel" }));
  fireEvent.click(screen.getByRole("button", { name: "document_template_upload" }));
  await expectNoAxeViolations(document.body);
});

it("keeps a rename target and its draft through list refresh, failure and retry", async () => {
  let items = [template];
  get.mockImplementation(() => ok({ items, runtime_configured: true }));
  patch.mockResolvedValueOnce({
    error: { message: "Try later" },
    response: new Response("{}", { status: 503 })
  });
  patch.mockImplementation(
    (_path: string, options: { params: { path: { id: string } }; body: { name: string } }) => {
      items = [{ ...template, name: options.body.name }];
      return ok(items[0]);
    }
  );
  const client = show();
  fireEvent.click(await screen.findByRole("button", { name: "actions: Municipal report" }));
  fireEvent.click(screen.getByRole("menuitem", { name: "document_template_rename" }));
  const dialog = screen.getByRole("dialog", { name: "document_template_rename" });
  items = [
    { ...template, id: "other", name: "Another report" },
    { ...template, name: "Refreshed name" }
  ];
  act(() => client.setQueryData(DOCUMENT_TEMPLATES_KEY, { items, runtime_configured: true }));
  await screen.findByText("Another report");
  expect((within(dialog).getByRole("textbox") as HTMLInputElement).value).toBe("Municipal report");
  fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: " Reviewed title " } });
  fireEvent.click(within(dialog).getByRole("button", { name: "document_template_save" }));
  expect(await within(dialog).findByText("Try later")).toBeTruthy();
  expect((within(dialog).getByRole("textbox") as HTMLInputElement).value).toBe(" Reviewed title ");
  fireEvent.click(within(dialog).getByRole("button", { name: "document_template_save" }));
  await waitFor(() => expect(patch).toHaveBeenCalledTimes(2));
  for (const call of patch.mock.calls)
    expect(call).toEqual([
      "/api/v1/document-templates/{id}/",
      { params: { path: { id: template.id } }, body: { name: "Reviewed title" } }
    ]);
});

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <DocumentTemplatesSection />
    </QueryClientProvider>
  );
  return client;
}

it("uploads while the runtime is unconfigured, with a filename fallback and reviewed default choice", async () => {
  let items: DocumentTemplate[] = [];
  get.mockImplementation(() => ok({ items, runtime_configured: false }));
  post.mockImplementation((_path: string, options: { body: FormData }) => {
    items = [{ ...template, name: String(options.body.get("name")) }];
    return ok(items[0]);
  });
  show();
  fireEvent.click(await screen.findByRole("button", { name: "document_template_upload" }));
  const dialog = screen.getByRole("dialog", { name: "document_template_upload" });
  const file = new File(["document"], "Council.DOCX", {
    type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
  });
  fireEvent.change(dialog.querySelector('input[type="file"]')!, { target: { files: [file] } });
  fireEvent.change(within(dialog).getByRole("textbox", { name: "document_template_name" }), {
    target: { value: "   " }
  });
  expect(
    (
      within(dialog).getByRole("checkbox", {
        name: "document_template_make_default_switch"
      }) as HTMLInputElement
    ).checked
  ).toBe(true);
  fireEvent.click(within(dialog).getByRole("button", { name: "document_template_save" }));
  expect(await screen.findByText("Council")).toBeTruthy();
  expect(post).toHaveBeenCalledTimes(1);
  const body = post.mock.calls[0]![1].body as FormData;
  expect(body.get("file")).toMatchObject({ name: file.name, size: file.size });
  expect(body.get("name")).toBe("Council");
  expect(body.get("is_default")).toBe("true");
});

it.each([
  ["report.pdf", 12, /not an accepted file type/i],
  ["report.docx", 5 * 1024 * 1024 + 1, /too large|exceeds|larger than/i]
] as const)("rejects %s locally before an upload request", async (name, size, message) => {
  get.mockImplementation(() => ok({ items: [], runtime_configured: false }));
  show();
  fireEvent.click(await screen.findByRole("button", { name: "document_template_upload" }));
  const dialog = screen.getByRole("dialog");
  fireEvent.change(dialog.querySelector('input[type="file"]')!, {
    target: {
      files: [new File([new Uint8Array(size)], name)]
    }
  });
  expect(
    (within(dialog).getByRole("button", { name: "document_template_save" }) as HTMLButtonElement)
      .disabled
  ).toBe(true);
  expect(await within(dialog).findByText(message)).toBeTruthy();
  await waitFor(() => expect(dialog.querySelector('[aria-invalid="true"]')).not.toBeNull());
  expect(post).not.toHaveBeenCalled();
});

it("keeps a failed upload's file and fields, and ignores a second press while saving", async () => {
  get.mockImplementation(() => ok({ items: [], runtime_configured: false }));
  let finish!: (value: unknown) => void;
  post.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      })
  );
  show();
  fireEvent.click(await screen.findByRole("button", { name: "document_template_upload" }));
  const dialog = screen.getByRole("dialog");
  fireEvent.change(dialog.querySelector('input[type="file"]')!, {
    target: { files: [new File(["content"], "report.docx")] }
  });
  fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "Reviewed name" } });
  fireEvent.click(within(dialog).getByRole("checkbox"));
  const save = within(dialog).getByRole("button", { name: "document_template_save" });
  save.focus();
  fireEvent.click(save);
  const pending = await within(dialog).findByRole("button", { name: "document_template_saving" });
  expect(pending).toBe(save);
  expect(pending.hasAttribute("disabled")).toBe(false);
  expect(document.activeElement).toBe(save);
  fireEvent.click(pending);
  expect(post).toHaveBeenCalledTimes(1);
  finish({ error: { message: "Storage offline" }, response: new Response("{}", { status: 503 }) });
  expect(await within(dialog).findByText("Storage offline")).toBeTruthy();
  expect((within(dialog).getByRole("textbox") as HTMLInputElement).value).toBe("Reviewed name");
  expect(within(dialog).getByText("report.docx")).toBeTruthy();
  expect((within(dialog).getByRole("checkbox") as HTMLInputElement).checked).toBe(false);
  post.mockImplementation(() => ok(template));
  fireEvent.click(within(dialog).getByRole("button", { name: "document_template_save" }));
  await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
  const retry = post.mock.calls[1]![1].body as FormData;
  expect(retry.get("name")).toBe("Reviewed name");
  expect(retry.get("is_default")).toBe("false");
});

it("rejects a filename fallback longer than the120-character name contract", async () => {
  get.mockImplementation(() => ok({ items: [], runtime_configured: true }));
  show();
  fireEvent.click(await screen.findByRole("button", { name: "document_template_upload" }));
  const dialog = screen.getByRole("dialog");
  fireEvent.change(dialog.querySelector('input[type="file"]')!, {
    target: { files: [new File(["content"], `${"a".repeat(121)}.docx`)] }
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "document_template_save" }));
  expect(await within(dialog).findByText("document_template_name_too_long")).toBeTruthy();
  expect(document.activeElement).toBe(within(dialog).getByRole("textbox"));
  expect(post).not.toHaveBeenCalled();
});

it("lists Word template defaults and inspection states, and expands checks and fields", async () => {
  get.mockImplementation(() =>
    ok({
      items: [
        template,
        {
          ...template,
          id: "unchecked",
          name: "Uninspected report",
          status: "unchecked",
          is_default: false
        },
        { ...template, id: "invalid", name: "Empty report", status: "invalid", is_default: false }
      ],
      runtime_configured: true
    })
  );
  show();
  const list = await screen.findByRole("list", { name: "document_templates" });
  const row = within(list).getByText("Municipal report").closest("li")!;
  expect(within(row).getByText("document_template_default")).toBeTruthy();
  expect(within(row).getByText("document_template_status_ready")).toBeTruthy();
  expect(within(list).getByText("document_template_status_unchecked")).toBeTruthy();
  expect(within(list).getByText("document_template_status_invalid")).toBeTruthy();
  fireEvent.click(within(row).getByRole("button", { name: "document_template_show_checks" }));
  expect(await within(row).findByText("Heading 2 is missing")).toBeTruthy();
  expect(within(row).getByText("case_number")).toBeTruthy();
  expect(within(row).getByText(/document_template_field_assistant/)).toBeTruthy();
});

it("shows an unsupported backend separately from an ordinary failure that can be retried", async () => {
  get.mockImplementation(() =>
    Promise.resolve({
      error: { message: "Not supported" },
      response: new Response("{}", { status: 404 })
    })
  );
  show();
  expect(await screen.findByText("document_template_not_supported")).toBeTruthy();
  expect(screen.queryByRole("list", { name: "document_templates" })).toBeNull();
  cleanup();
  get.mockResolvedValueOnce({
    error: { message: "Service unavailable" },
    response: new Response("{}", { status: 503 })
  });
  get.mockImplementation(() => ok({ items: [], runtime_configured: false }));
  show();
  expect(await screen.findByText("Service unavailable")).toBeTruthy();
  expect(screen.queryByText("document_template_not_supported")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "query_error_retry_named" }));
  expect(await screen.findByText("document_template_empty")).toBeTruthy();
});
