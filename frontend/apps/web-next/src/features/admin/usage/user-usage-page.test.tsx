// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));

const model = {
  model_id: "model-1",
  model_name: "gpt-5",
  model_nickname: "GPT-5",
  model_org: "OpenAI",
  model_provider: "Azure",
  input_token_usage: 1200,
  output_token_usage: 300,
  total_token_usage: 1500,
  request_count: 4
};

const apiState = vi.hoisted(() => ({ failSummary: false }));

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (path: string) => {
      if (apiState.failSummary && path === "/api/v1/token-usage/users/{user_id}/summary") {
        return Promise.resolve({
          error: { message: "Database unavailable" },
          response: new Response(null, { status: 503 })
        });
      }
      const data =
        path === "/api/v1/token-usage/users/{user_id}/summary"
          ? {
              user: {
                user_id: "user-1",
                username: "Anna Lind",
                email: "anna.lind@example.se",
                total_input_tokens: 1200,
                total_output_tokens: 300,
                total_tokens: 1500,
                total_requests: 4,
                models_used: [model]
              }
            }
          : path === "/api/v1/token-usage/users/{user_id}"
            ? {
                total_token_usage: 1500,
                total_input_token_usage: 1200,
                total_output_token_usage: 300,
                models: [model]
              }
            : path === "/api/v1/ai-models/"
              ? { completion_models: [], embedding_models: [], transcription_models: [] }
              : {};
      return Promise.resolve({ data, response: new Response("{}") });
    }
  }
}));

import { UserUsagePage } from "./user-usage-page";

afterEach(() => {
  cleanup();
  apiState.failSummary = false;
});

describe("UserUsagePage", () => {
  it("leads back to the users list it was opened from", async () => {
    renderInApp(
      <UserUsagePage userId="user-1" initialRange={{ from: "2026-09-01", to: "2026-09-25" }} />,
      {
        route:
          "/admin/usage/users/user-1?tab=users&from=2026-09-01&to=2026-09-25&page=3&sortBy=requests&sortOrder=asc&userSearch=anna"
      }
    );

    await screen.findByRole("table", { name: "Fullständig modelluppdelning" });
    expect(screen.getByRole("link", { name: "Tillbaka" }).getAttribute("href")).toBe(
      "/admin/usage?tab=users&from=2026-09-01&to=2026-09-25&page=3&sortBy=requests&sortOrder=asc&userSearch=anna"
    );
  });

  it("names the model table by its heading", async () => {
    renderInApp(
      <UserUsagePage userId="user-1" initialRange={{ from: "2026-09-01", to: "2026-09-25" }} />
    );

    const table = await screen.findByRole("table", { name: "Fullständig modelluppdelning" });
    expect(within(table).getByText("GPT-5")).toBeTruthy();
  });

  it("names each usage bar after its provider or model", async () => {
    const { container } = renderInApp(
      <UserUsagePage userId="user-1" initialRange={{ from: "2026-09-01", to: "2026-09-25" }} />
    );

    await screen.findByRole("table", { name: "Fullständig modelluppdelning" });
    expect(screen.getByRole("progressbar", { name: "Azure" })).toBeTruthy();
    expect(screen.getByRole("progressbar", { name: "GPT-5" })).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("reports a failed read as an error with a retry, not as a missing user", async () => {
    apiState.failSummary = true;
    renderInApp(
      <UserUsagePage userId="user-1" initialRange={{ from: "2026-09-01", to: "2026-09-25" }} />
    );

    const message = await screen.findByText("Database unavailable");
    expect(message.closest('[role="alert"]')).not.toBeNull();
    expect(screen.queryByText("Användaren hittades inte")).toBeNull();

    apiState.failSummary = false;
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(await screen.findByRole("table", { name: "Fullständig modelluppdelning" })).toBeTruthy();
  });
});
