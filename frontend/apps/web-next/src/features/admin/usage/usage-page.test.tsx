// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

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

const apiState = vi.hoisted(() => ({ failingPaths: new Set<string>() }));

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (path: string) => {
      if (apiState.failingPaths.has(path)) {
        return Promise.resolve({
          error: {
            error: "Internal server error",
            error_id: "8bc91e0a",
            message:
              "An unexpected error occurred. Please try again or contact support with the error_id."
          },
          response: new Response("{}", { status: 500, headers: { "x-trace-id": "trace-123" } })
        });
      }
      const data =
        path === "/api/v1/token-usage/"
          ? {
              total_token_usage: 1500,
              total_input_token_usage: 1200,
              total_output_token_usage: 300,
              models: [
                model,
                { ...model, model_id: "model-2", model_nickname: "GPT-5 (annan konfiguration)" }
              ]
            }
          : path === "/api/v1/token-usage/users"
            ? {
                total_users: 1,
                total_tokens: 1500,
                total_requests: 4,
                users: [
                  {
                    user_id: "user-1",
                    username: "Anna Lind",
                    email: "anna.lind@example.se",
                    total_input_tokens: 1200,
                    total_output_tokens: 300,
                    total_tokens: 1500,
                    total_requests: 4,
                    models_used: [model]
                  }
                ]
              }
            : path === "/api/v1/storage/"
              ? { total_used: 2048, personal_used: 1024, shared_used: 1024 }
              : path === "/api/v1/storage/spaces/"
                ? {
                    items: [
                      { id: "space-1", name: "Upphandling", size: 1024 },
                      { id: "space-2", name: "Upphandling", size: 1024 }
                    ]
                  }
                : path === "/api/v1/ai-models/"
                  ? { completion_models: [], embedding_models: [], transcription_models: [] }
                  : {};
      return Promise.resolve({ data, response: new Response("{}") });
    }
  }
}));

import { UsagePage } from "./usage-page";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  apiState.failingPaths.clear();
});

describe("UsagePage", () => {
  it("keeps same-named models distinct and names each tab's table", async () => {
    const consoleError = vi.spyOn(console, "error");
    const { container } = renderInApp(<UsagePage />);

    const tokens = await screen.findByRole("table", { name: "Tokens" });
    expect(within(tokens).getByText("GPT-5")).toBeTruthy();
    expect(within(tokens).getByText("GPT-5 (annan konfiguration)")).toBeTruthy();
    expect(consoleError.mock.calls.flat().join(" ")).not.toContain("same key");
    await expectNoAxeViolations(container);

    // Radix tabs switch on mouse down.
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Användare" }));
    const users = await screen.findByRole("table", { name: "Användare" });
    expect(within(users).getByRole("link", { name: /Anna Lind/ })).toBeTruthy();

    fireEvent.mouseDown(screen.getByRole("tab", { name: "Lagring" }));
    const storage = await screen.findByRole("table", { name: "Lagring" });
    expect(within(storage).getAllByText("Upphandling")).toHaveLength(2);
    expect(consoleError.mock.calls.flat().join(" ")).not.toContain("same key");
  });

  it("keeps the other tabs usable when token usage fails and retries that tab", async () => {
    apiState.failingPaths.add("/api/v1/token-usage/");
    const { container } = renderInApp(<UsagePage />);

    expect(await screen.findByText("Fel-ID: 8bc91e0a")).toBeTruthy();
    expect(screen.getByText("Vi upplever vissa svårigheter, försök igen senare.")).toBeTruthy();
    await expectNoAxeViolations(container);

    fireEvent.mouseDown(screen.getByRole("tab", { name: "Lagring" }));
    expect(await screen.findByRole("table", { name: "Lagring" })).toBeTruthy();

    fireEvent.mouseDown(screen.getByRole("tab", { name: "Tokens" }));
    expect(await screen.findByRole("button", { name: "Försök igen" })).toBeTruthy();
    apiState.failingPaths.delete("/api/v1/token-usage/");
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(await screen.findByRole("table", { name: "Tokens" })).toBeTruthy();
  });

  it("retries a failed storage request without losing tokens", async () => {
    apiState.failingPaths.add("/api/v1/storage/spaces/");
    renderInApp(<UsagePage />);

    expect(await screen.findByRole("table", { name: "Tokens" })).toBeTruthy();
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Lagring" }));
    expect(await screen.findByText("Fel-ID: 8bc91e0a")).toBeTruthy();

    apiState.failingPaths.delete("/api/v1/storage/spaces/");
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(await screen.findByRole("table", { name: "Lagring" })).toBeTruthy();

    fireEvent.mouseDown(screen.getByRole("tab", { name: "Tokens" }));
    expect(await screen.findByRole("table", { name: "Tokens" })).toBeTruthy();
  });

  it("shows and retries an error on the users tab", async () => {
    apiState.failingPaths.add("/api/v1/token-usage/users");
    renderInApp(<UsagePage />);

    fireEvent.mouseDown(screen.getByRole("tab", { name: "Användare" }));
    expect(await screen.findByText("Fel-ID: 8bc91e0a")).toBeTruthy();

    apiState.failingPaths.delete("/api/v1/token-usage/users");
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(await screen.findByRole("table", { name: "Användare" })).toBeTruthy();
  });
});
