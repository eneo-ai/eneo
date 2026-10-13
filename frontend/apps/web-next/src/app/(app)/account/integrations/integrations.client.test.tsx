// @vitest-environment jsdom
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { AccountIntegrations } from "./integrations.client";
const get = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: { GET: get } }));
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});
it("shows a retryable failure before showing a successfully loaded empty list", async () => {
  get.mockResolvedValueOnce({
    error: { message: "Unavailable" },
    response: new Response("{}", { status: 500 })
  });
  get.mockResolvedValue({ data: { items: [] }, response: new Response("{}") });
  renderInApp(<AccountIntegrations />);
  const retry = await screen.findByRole("button", { name: "Försök igen" });
  expect(screen.queryByText("Inga resultat hittades")).toBeNull();
  fireEvent.click(retry);
  expect(await screen.findByText("Inga resultat hittades")).toBeTruthy();
});
