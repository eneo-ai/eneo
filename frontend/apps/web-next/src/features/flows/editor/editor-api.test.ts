// @vitest-environment jsdom
import { focusManager, QueryObserver } from "@tanstack/react-query";
import { afterEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { testQueryClient } from "@/test/render";
import { flowEditorKeys, templateInspectionQueryOptions } from "./editor-api";

const INSPECT = "GET /api/v1/flows/{id}/template-inspect/";
const state = vi.hoisted(() => ({
  routes: {} as Record<string, (init: never) => { status?: number; body: unknown }>,
  stub: null as unknown as ReturnType<typeof import("./testing/fixtures").apiStub>
}));
vi.mock("@/lib/api/browser", async () => {
  const { apiStub } = await import("./testing/fixtures");
  state.stub = apiStub(new Proxy({}, { get: (_target, key: string) => state.routes[key] }));
  return { browserApi: state.stub.client };
});

const inspection = {
  file_name: "mall.docx",
  syntax: "jinja",
  placeholders: [{ name: "namn" }],
  checks: [],
  language: "sv"
};
const inspections = () =>
  state.stub.calls.filter((call) => call.path === "/api/v1/flows/{id}/template-inspect/").length;

afterEach(() => {
  vi.useRealTimers();
  state.stub.calls.length = 0;
  focusManager.setFocused(undefined);
});

describe("templateInspectionQueryOptions", () => {
  it("keeps a template's inspection while cached: a stored template's bytes never change", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    state.routes[INSPECT] = () => ({ body: inspection });
    const client = testQueryClient();
    // Mounted, as the app's provider does, so window focus reaches the client.
    client.mount();
    onTestFinished(() => client.unmount());
    const observer = new QueryObserver(client, templateInspectionQueryOptions("flow-1", "asset-1"));
    const stop = observer.subscribe(() => {});
    await vi.waitFor(() => expect(observer.getCurrentResult().data).toEqual(inspection));

    // Long past the app's 30 s default: refocusing the window reads the cache…
    vi.setSystemTime(Date.now() + 10 * 60_000);
    focusManager.setFocused(false);
    focusManager.setFocused(true);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(observer.getCurrentResult().isFetching).toBe(false);
    expect(inspections()).toBe(1);

    // …and so does choosing the template again.
    await client.query(templateInspectionQueryOptions("flow-1", "asset-1"));
    expect(inspections()).toBe(1);

    // Another template is inspected on its own.
    await client.query(templateInspectionQueryOptions("flow-1", "asset-2"));
    expect(inspections()).toBe(2);

    // An explicit invalidation still inspects again.
    await client.invalidateQueries({
      queryKey: flowEditorKeys.templateInspection("flow-1", "asset-1")
    });
    await vi.waitFor(() => expect(inspections()).toBe(3));
    stop();
  });

  it("inspects again after a failed inspection", async () => {
    let fail = true;
    state.routes[INSPECT] = () =>
      fail
        ? { status: 400, body: { message: "Invalid DOCX template.", code: "bad_request" } }
        : { body: inspection };
    const client = testQueryClient();
    await expect(
      client.query(templateInspectionQueryOptions("flow-1", "asset-1"))
    ).rejects.toThrow();

    fail = false;
    await expect(
      client.query(templateInspectionQueryOptions("flow-1", "asset-1"))
    ).resolves.toEqual(inspection);
    expect(inspections()).toBe(2);
  });
});
