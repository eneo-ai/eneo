// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp, testQueryClient } from "@/test/render";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import { SpaceProvider } from "@/features/spaces/use-space";
import { pendingImports, resetPendingImports } from "../import-completion";
import { IntegrationsTab } from "../tab";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
const jobs = vi.hoisted(() => ({ trackJob: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/jobs/use-jobs", () => ({ useJobs: () => jobs }));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  sessionStorage.clear();
  resetPendingImports();
});
const ok = (data: unknown) => ({ data, response: new Response("{}") });
function showTab() {
  const space = makeSpace();
  const queryClient = testQueryClient();
  queryClient.setQueryData(["spaces", "space-1"], space);
  api.GET.mockImplementation((path: string) =>
    Promise.resolve(
      ok(
        path === "/api/v1/spaces/{id}/"
          ? space
          : path.endsWith("/available/")
            ? {
                items: [
                  {
                    id: "connection",
                    tenant_integration_id: "tenant-connection",
                    name: "SharePoint",
                    description: "",
                    integration_type: "sharepoint",
                    auth_type: "tenant_app",
                    connected: true
                  }
                ]
              }
            : path.endsWith("/preview/")
              ? {
                  items: [
                    { key: "site", type: "site", name: "Intranätet", url: "https://sp/intra" }
                  ]
                }
              : { items: [], current_path: "/", drive_id: "drive" }
      )
    )
  );
  renderInApp(
    <SpaceProvider routeId="space-1">
      <IntegrationsTab canCreate name={{ "aria-label": "Integrationer" }} />
    </SpaceProvider>,
    { queryClient }
  );
  return { queryClient, space };
}
async function openImport() {
  fireEvent.click(await screen.findByRole("button", { name: "Importera kunskap" }));
  fireEvent.click(screen.getByRole("button", { name: "Fortsätt" }));
}
async function selectWholeSite() {
  fireEvent.click(await screen.findByRole("button", { name: "Intranätet" }));
  fireEvent.click(await screen.findByRole("checkbox", { name: "Importera hela webbplatsen" }));
}

it("keeps the pending SharePoint request across the tab's close, reopen and selector steps", async () => {
  let finish!: (value: ReturnType<typeof ok>) => void;
  api.POST.mockReturnValue(
    new Promise((resolve) => {
      finish = resolve;
    })
  );
  showTab();
  await openImport();
  await selectWholeSite();
  fireEvent.click(screen.getByRole("button", { name: "Importera" }));
  await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Stäng" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  await openImport();
  fireEvent.click(screen.getByRole("button", { name: "Tillbaka" }));
  fireEvent.click(screen.getByRole("button", { name: "Fortsätt" }));
  await selectWholeSite();
  fireEvent.change(screen.getByRole("textbox", { name: "Importnamn för Intranätet" }), {
    target: { value: "Ny draft" }
  });
  const submit = screen.getByRole("button", { name: /^(Importera|Importerar\.\.\.)$/ });
  await act(async () => {
    fireEvent.click(submit);
  });
  expect(api.POST).toHaveBeenCalledTimes(1);
  expect(submit.getAttribute("aria-busy")).toBe("true");
  const job = { id: "job-pending", status: "queued" };
  await act(async () => {
    finish(
      ok({
        created_count: 1,
        failed_count: 0,
        items: [
          {
            index: 0,
            name: "Intranätet",
            status: "created",
            integration_knowledge_id: "created-1",
            job
          }
        ]
      })
    );
  });
  await waitFor(() => expect(jobs.trackJob).toHaveBeenCalledWith([job]));
  expect(pendingImports()).toContainEqual(
    expect.objectContaining({ jobId: job.id, knowledgeId: "created-1" })
  );
  await screen.findByRole("button", { name: "Importera" });
  expect(screen.queryByRole("heading", { name: "Import köad" })).toBeNull();
  expect(screen.getByRole("textbox", { name: "Importnamn för Intranätet" })).toHaveProperty(
    "value",
    "Ny draft"
  );
});

it.each(["delayed", "failed", "all-failed"])(
  "links directly to a created source with a %s space refresh",
  async (mode) => {
    const { queryClient, space } = showTab();
    const get = api.GET.getMockImplementation()!;
    let release = () => {};
    const refresh =
      mode === "delayed"
        ? new Promise((resolve) => {
            release = () => resolve(ok(space));
          })
        : Promise.resolve({
            error: { detail: "Unavailable" },
            response: new Response("{}", { status: 503 })
          });
    api.GET.mockImplementation((path: string) =>
      path === "/api/v1/spaces/{id}/"
        ? refresh
        : path.endsWith("/tree/")
          ? Promise.resolve(
              ok({
                items: [
                  { id: "a", type: "file", name: "A.pdf", path: "/A.pdf" },
                  { id: "b", type: "file", name: "B.pdf", path: "/B.pdf" }
                ],
                current_path: "/",
                drive_id: "drive"
              })
            )
          : get(path)
    );
    const allFailed = mode === "all-failed";
    api.POST.mockResolvedValue(
      ok({
        created_count: allFailed ? 0 : 2,
        failed_count: allFailed ? 2 : 0,
        items: ["a", "b"].map((id, index) =>
          allFailed
            ? { index, name: id, status: "failed", error: "Nekad" }
            : { index, name: id, status: "created", integration_knowledge_id: `created-${id}` }
        )
      })
    );
    await openImport();
    fireEvent.click(await screen.findByRole("button", { name: "Intranätet" }));
    for (const name of ["A.pdf", "B.pdf"])
      fireEvent.click(await screen.findByRole("checkbox", { name }));
    fireEvent.change(screen.getByRole("textbox", { name: /^Gruppnamn/ }), {
      target: { value: "Rapporter" }
    });
    fireEvent.click(screen.getByRole("button", { name: "Importera" }));
    try {
      await waitFor(() =>
        expect(queryClient.getQueryState(["spaces", "space-1"])).toMatchObject(
          mode === "delayed" ? { fetchStatus: "fetching" } : { status: "error" }
        )
      );
      if (allFailed) {
        expect(screen.queryByRole("link", { name: "Visa importen" })).toBeNull();
        expect(screen.getByRole("button", { name: "Försök igen" })).toBeTruthy();
      } else {
        expect(screen.getByRole("link", { name: "Visa importen" }).getAttribute("href")).toBe(
          "/spaces/space-1/knowledge/integrations/created-a"
        );
      }
    } finally {
      await act(async () => {
        release();
      });
    }
  }
);
