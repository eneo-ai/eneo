import { QueryClient } from "@tanstack/react-query";
import createClient from "openapi-fetch";
import { expect, it, vi } from "vitest";
import type { paths } from "@/lib/api/schema";
import { bundledToolsQueryOptions } from "./mcp";

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const catalogue = {
  items: [{ tool: "charts", purpose: "charts", available: true, mcp_server_id: null }],
  count: 1,
  runtime: null
};

it("reads a backend without the bundled runtime as an empty catalogue", async () => {
  const fetch = vi.fn().mockResolvedValue(json(404, { detail: "Not Found" }));
  const api = createClient<paths>({ baseUrl: "http://localhost", fetch });
  expect(await new QueryClient().query(bundledToolsQueryOptions(api))).toEqual({
    items: [],
    count: 0,
    runtime: null
  });
});

it.each([403, 500])("keeps a %s an error instead of an empty catalogue", async (status) => {
  const fetch = vi.fn().mockResolvedValue(json(status, { message: "Refused" }));
  const api = createClient<paths>({ baseUrl: "http://localhost", fetch });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await expect(client.query(bundledToolsQueryOptions(api))).rejects.toMatchObject({ status });
});

it("recovers on the next read after a server failure", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(json(500, { message: "Runtime down" }))
    .mockResolvedValue(json(200, catalogue));
  const api = createClient<paths>({ baseUrl: "http://localhost", fetch });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await expect(client.query(bundledToolsQueryOptions(api))).rejects.toMatchObject({ status: 500 });
  expect(await client.query(bundledToolsQueryOptions(api))).toEqual(catalogue);
});
