// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { sessionKeys } from "@/lib/api/session";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";
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
  // The user (quota) answers at once; the collection's files wait for the test.
  api.GET.mockImplementation((path: string) =>
    path === "/api/v1/users/me/"
      ? Promise.resolve({ data: appContext.user, response: new Response("{}") })
      : new Promise((resolve) => {
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

// The backend computes the quota live: deleting files, or uploading in another
// tab, moves it without touching this tab's cache. Each opening asks afresh.
it("checks the quota against a fresh answer each time it opens", async () => {
  const atQuota = { ...appContext.user, quota_limit: 100, quota_used: 100 };
  let quotaUsed = 100;
  api.GET.mockImplementation(async (path: string) => ({
    data: path === "/api/v1/users/me/" ? { ...atQuota, quota_used: quotaUsed } : { items: [] },
    response: new Response("{}")
  }));
  // The session as loaded: the user at quota, in the app context and its query.
  const queryClient = testQueryClient();
  queryClient.setQueryData(sessionKeys.me, atQuota);
  const dialog = (open: boolean) => (
    <UploadBlobsDialog
      collectionId="collection-1"
      collectionName="Protokoll"
      open={open}
      onOpenChange={() => {}}
    />
  );
  const { rerender } = renderInApp(dialog(true), {
    appContext: { ...appContext, user: atQuota },
    queryClient
  });
  const full = () => screen.queryByText(/Lagringsutrymmet är fullt/);
  const choose = () =>
    fireEvent.change(screen.getByLabelText("Dra och släpp filer eller mappar här"), {
      target: { files: [pdf("protokoll.pdf", 10)] }
    });
  choose();
  await waitFor(() => expect(full()).not.toBeNull());

  // Files deleted since: the backend's answer changes, the cache does not.
  quotaUsed = 0;
  rerender(dialog(false));
  rerender(dialog(true));
  choose();

  await waitFor(() => expect(full()).toBeNull());
});
