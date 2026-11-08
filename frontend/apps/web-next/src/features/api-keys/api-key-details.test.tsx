// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";

const api = vi.hoisted(() => ({ GET: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

import { ApiKeyDetailsDialog } from "./api-key-details";

afterEach(cleanup);

const apiKey = {
  id: "key-1",
  name: "Diariet",
  key_prefix: "eneo_",
  key_suffix: "a1b2"
} as Parameters<typeof ApiKeyDetailsDialog>[0]["apiKey"];

it("says the usage could not be read, not that the key has none", async () => {
  api.GET.mockResolvedValue({
    error: { message: "Usage store unavailable" },
    response: new Response(null, { status: 503 })
  });
  renderInApp(
    <ApiKeyDetailsDialog apiKey={apiKey} mode="admin" tab="usage" open onOpenChange={() => {}} />
  );

  const message = await screen.findByText("Usage store unavailable");
  expect(message.closest('[role="alert"]')).not.toBeNull();
  expect(screen.getByRole("button", { name: /^Försök igen/ })).toBeTruthy();
  expect(screen.queryByText("Inga användningshändelser hittades för den här nyckeln.")).toBeNull();
});
