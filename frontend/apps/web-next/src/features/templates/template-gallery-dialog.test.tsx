// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { renderInApp, testAppContext } from "@/test/render";
import { TemplateGalleryDialog } from "./template-gallery-dialog";
const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), DELETE: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
beforeEach(() => {
  api.GET.mockResolvedValue({
    data: {
      items: [
        {
          id: "template",
          name: "Protokoll",
          description: null,
          wizard: { attachments: { required: true } }
        }
      ]
    },
    response: new Response("{}")
  });
  api.POST.mockResolvedValue({ data: { id: "uploaded" }, response: new Response("{}") });
  api.DELETE.mockResolvedValue({ data: null, response: new Response(null, { status: 204 }) });
});
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

async function show(onCreate: () => Promise<void> = async () => {}) {
  const result = renderInApp(
    <TemplateGalleryDialog
      templateKind="app"
      createLabel="Skapa app"
      open
      pending={false}
      onOpenChange={vi.fn()}
      onCreate={onCreate}
    />,
    {
      appContext: testAppContext({
        limits: {
          attachments: {
            formats: [
              { mimetype: "application/pdf", size: 10000, extensions: ["pdf"], vision: false }
            ]
          }
        }
      })
    }
  );
  fireEvent.click(await screen.findByRole("button", { name: /Protokoll/ }));
  fireEvent.click(screen.getByRole("button", { name: "Nästa" }));
  const picker = screen.getByRole("dialog").querySelector<HTMLInputElement>('input[type="file"]')!;
  fireEvent.change(picker, {
    target: { files: [new File(["pdf"], "notes.pdf", { type: "application/pdf" })] }
  });
  await screen.findByText("notes.pdf");
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Ladda upp filer" }).getAttribute("aria-busy")
    ).toBeNull()
  );
  return result;
}
it("deletes temporary attachments when the explicit Cancel button is used", async () => {
  await show();
  fireEvent.click(screen.getByRole("button", { name: "Avbryt" }));
  await waitFor(() =>
    expect(api.DELETE).toHaveBeenCalledExactlyOnceWith("/api/v1/files/{id}/", {
      params: { path: { id: "uploaded" } }
    })
  );
});
it("transfers submitted files before creation can unmount the form", async () => {
  let finish!: () => void;
  const create = vi.fn(
    () =>
      new Promise<void>((resolve) => {
        finish = resolve;
      })
  );
  const { unmount } = await show(create);
  fireEvent.click(screen.getByRole("button", { name: "Skapa app" }));
  expect(create).toHaveBeenCalledTimes(1);
  unmount();
  await act(async () => finish());
  expect(api.DELETE).not.toHaveBeenCalled();
});
