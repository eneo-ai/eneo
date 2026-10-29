import { isNotFound, isRedirect, redirect } from "@tanstack/react-router";
import { beforeEach, expect, it, vi } from "vitest";
import { testAppContext, testQueryClient } from "@/test/render";
import { EneoApiError } from "./api/errors";
import { sessionKeys, sessionQueries } from "./api/session";
import { browserApi } from "./api/browser";
import { notFoundOn404, requirePermission } from "./route-helpers";

const get = vi.hoisted(() => vi.fn());
vi.mock("./api/browser", () => ({ browserApi: { GET: get } }));

beforeEach(() => {
  get.mockReset();
});

it("maps a missing resource to the router's not-found state", async () => {
  const result = await notFoundOn404(
    Promise.reject(new EneoApiError("Missing", { status: 404 }))
  ).catch((error: unknown) => error);
  expect(isNotFound(result)).toBe(true);
});

it("keeps successful data and unrelated failures unchanged", async () => {
  const resource = { name: "Resource" };
  expect(await notFoundOn404(Promise.resolve(resource))).toBe(resource);
  for (const error of [new EneoApiError("Unavailable", { status: 500 }), redirect({ href: "/" })]) {
    await expect(notFoundOn404(Promise.reject(error))).rejects.toBe(error);
  }
});

it("reads permission evidence once through the shared me query", async () => {
  const user = testAppContext({ permissions: ["admin"] }).user;
  get.mockResolvedValue({ data: user, response: new Response() });
  const context = { queryClient: testQueryClient() };
  await expect(requirePermission(context, "admin", "/spaces/list")).resolves.toBeUndefined();
  await expect(requirePermission(context, "admin", "/spaces/list")).resolves.toBeUndefined();
  expect(get).toHaveBeenCalledExactlyOnceWith("/api/v1/users/me/");
  expect(context.queryClient.getQueryData(sessionKeys.me)).toEqual(user);
});

it("redirects a missing permission without a second me request", async () => {
  const context = { queryClient: testQueryClient() };
  context.queryClient.setQueryData(sessionKeys.me, testAppContext({ permissions: [] }).user);
  const result = await requirePermission(context, "admin", "/spaces/list").catch(
    (error: unknown) => error
  );
  expect(isRedirect(result)).toBe(true);
  if (!isRedirect(result)) throw new Error("Expected permission redirect");
  expect(result.options).toMatchObject({ href: "/spaces/list", replace: true });
  expect(get).not.toHaveBeenCalled();
});

it("uses cached permission evidence after a failed refresh", async () => {
  const context = { queryClient: testQueryClient() };
  context.queryClient.setQueryData(sessionKeys.me, testAppContext({ permissions: ["admin"] }).user);
  const failure = new Error("Offline");
  get.mockRejectedValue(failure);
  await context.queryClient.invalidateQueries({ queryKey: sessionKeys.me, refetchType: "none" });
  await expect(context.queryClient.query(sessionQueries(browserApi).me)).rejects.toBe(failure);
  get.mockClear();
  await expect(requirePermission(context, "admin", "/spaces/list")).resolves.toBeUndefined();
  expect(get).not.toHaveBeenCalled();
});
