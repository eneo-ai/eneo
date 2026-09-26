// @vitest-environment jsdom
import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
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

afterEach(cleanup);

describe("UserUsagePage", () => {
  it("names the model table by its heading", async () => {
    renderInApp(
      <UserUsagePage userId="user-1" initialRange={{ from: "2026-09-01", to: "2026-09-25" }} />
    );

    const table = await screen.findByRole("table", { name: "Fullständig modelluppdelning" });
    expect(within(table).getByText("GPT-5")).toBeTruthy();
  });
});
