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

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (path: string) => {
      const data =
        path === "/api/v1/token-usage/"
          ? {
              total_token_usage: 1500,
              total_input_token_usage: 1200,
              total_output_token_usage: 300,
              models: [model]
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
                ? { items: [{ name: "Upphandling", size: 1024 }] }
                : path === "/api/v1/ai-models/"
                  ? { completion_models: [], embedding_models: [], transcription_models: [] }
                  : {};
      return Promise.resolve({ data, response: new Response("{}") });
    }
  }
}));

import { UsagePage } from "./usage-page";

afterEach(cleanup);

describe("UsagePage", () => {
  it("names each tab's table after the tab", async () => {
    const { container } = renderInApp(<UsagePage />);

    const tokens = await screen.findByRole("table", { name: "Tokens" });
    expect(within(tokens).getByText("GPT-5")).toBeTruthy();
    await expectNoAxeViolations(container);

    // Radix tabs switch on mouse down.
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Användare" }));
    const users = await screen.findByRole("table", { name: "Användare" });
    expect(within(users).getByRole("link", { name: /Anna Lind/ })).toBeTruthy();

    fireEvent.mouseDown(screen.getByRole("tab", { name: "Lagring" }));
    const storage = await screen.findByRole("table", { name: "Lagring" });
    expect(within(storage).getByText("Upphandling")).toBeTruthy();
  });
});
