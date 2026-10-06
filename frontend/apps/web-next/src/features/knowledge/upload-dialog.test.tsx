// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp, testAppContext } from "@/test/render";
import { UploadBlobsDialog } from "./upload-dialog";

const api = vi.hoisted(() => ({ GET: vi.fn() }));
const queueUploads = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/features/jobs/use-jobs", () => ({ useJobs: () => ({ queueUploads }) }));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const appContext = testAppContext({
  limits: {
    info_blobs: {
      formats: [{ mimetype: "application/pdf", extensions: ["pdf"], size: 1000, vision: false }]
    }
  }
});

function show() {
  renderInApp(
    <UploadBlobsDialog
      collectionId="collection-1"
      collectionName="Protokoll"
      open
      onOpenChange={() => {}}
    />,
    { appContext }
  );
  return {
    upload: screen.getByRole("button", { name: "Ladda upp filer" }),
    field: screen.getByLabelText("Dra och släpp filer eller mappar här")
  };
}

const described = (field: HTMLElement) =>
  (field.getAttribute("aria-describedby") ?? "")
    .split(" ")
    .map((id) => document.getElementById(id)?.textContent);

const pdf = (name: string, bytes: number) =>
  new File(["x".repeat(bytes)], name, { type: "application/pdf" });

it("shows a missing or too large file at the file field on upload, which takes focus", () => {
  api.GET.mockResolvedValue({ data: { items: [] }, response: new Response("{}") });
  const { upload, field } = show();
  expect(upload.hasAttribute("disabled")).toBe(false);

  fireEvent.click(upload);
  expect(document.activeElement).toBe(field);
  expect(field.getAttribute("aria-invalid")).toBe("true");
  expect(described(field)).toEqual(["Välj minst en fil att ladda upp."]);

  fireEvent.change(field, { target: { files: [pdf("budget.pdf", 2000)] } });
  upload.focus();
  fireEvent.click(upload);
  expect(document.activeElement).toBe(field);
  expect(field.getAttribute("aria-invalid")).toBe("true");
  expect(described(field)).toEqual([expect.stringContaining("budget.pdf: Filen är för stor")]);
  expect(queueUploads).not.toHaveBeenCalled();
});

it("waits for the collection's files on upload, keeping focus on the busy button", async () => {
  let loaded: (value: unknown) => void = () => {};
  api.GET.mockImplementation(
    () =>
      new Promise((resolve) => {
        loaded = resolve;
      })
  );
  const { upload, field } = show();
  const protocol = pdf("protokoll.pdf", 10);
  fireEvent.change(field, { target: { files: [protocol] } });

  upload.focus();
  fireEvent.click(upload);
  await waitFor(() => expect(upload.getAttribute("aria-busy")).toBe("true"));
  expect(upload.hasAttribute("disabled")).toBe(false);
  expect(document.activeElement).toBe(upload);
  expect(queueUploads).not.toHaveBeenCalled();

  loaded({ data: { items: [] }, response: new Response("{}") });
  await waitFor(() => expect(queueUploads).toHaveBeenCalledWith("collection-1", [protocol]));
});
