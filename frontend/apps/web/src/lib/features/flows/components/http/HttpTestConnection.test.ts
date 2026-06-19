// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";

import HttpTestConnection from "./HttpTestConnection.svelte";
import type { HttpAuthoredConfig } from "./httpConfigTypes";

function makeConfig(overrides: Partial<HttpAuthoredConfig> = {}): HttpAuthoredConfig {
  return {
    url: "{{base_url}}/hook",
    auth: { mode: "none" },
    timeout_seconds: 30,
    body: { mode: "text_template", template: "hello {{name}}" },
    custom_headers: [],
    response_format: null,
    ...overrides
  };
}

function renderHttpTestConnection(config = makeConfig()) {
  return render(HttpTestConnection, {
    props: {
      config,
      direction: "output",
      method: "POST",
      flowId: "flow-1",
      isPublished: false
    }
  });
}

function stubFetch(
  payload: unknown,
  options: { ok?: boolean; status?: number; statusText?: string } = {}
) {
  const response = {
    ok: options.ok ?? true,
    status: options.status ?? 200,
    statusText: options.statusText ?? "OK",
    json: vi.fn(async () => payload)
  };
  const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => {
    return response as unknown as Response;
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("HttpTestConnection", () => {
  it("keeps the variables editor hidden for literal configs", () => {
    renderHttpTestConnection(
      makeConfig({ url: "https://api.example.com/hook", body: { mode: "none" } })
    );

    expect(screen.queryByLabelText(m.http_test_variables_label())).toBeNull();
  });

  it("ignores stale hidden variables after the config changes to a literal URL", async () => {
    const fetchMock = stubFetch({ success: true, status_code: 204 });
    const { rerender } = renderHttpTestConnection();

    await fireEvent.input(screen.getByLabelText(m.http_test_variables_label()), {
      target: { value: "{bad" }
    });

    await rerender({
      config: makeConfig({ url: "https://api.example.com/hook", body: { mode: "none" } }),
      direction: "output",
      method: "POST",
      flowId: "flow-1",
      isPublished: false
    });
    await fireEvent.click(screen.getByRole("button", { name: m.http_test_button() }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const firstCall = fetchMock.mock.calls[0];
    if (!firstCall) throw new Error("Expected HTTP test fetch call");
    const init = firstCall[1];
    if (!init) throw new Error("Expected HTTP test fetch init");
    const body = JSON.parse(String(init.body));

    expect(body.test_variables).toEqual({});
  });

  it("submits parsed test variables with the authored HTTP config", async () => {
    const fetchMock = stubFetch({ success: true, status_code: 204 });
    renderHttpTestConnection();

    await fireEvent.input(screen.getByLabelText(m.http_test_variables_label()), {
      target: { value: '{"base_url":"https://api.example.com","name":"Alex"}' }
    });
    await fireEvent.click(screen.getByRole("button", { name: m.http_test_button() }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const firstCall = fetchMock.mock.calls[0];
    if (!firstCall) throw new Error("Expected HTTP test fetch call");
    const init = firstCall[1];
    if (!init) throw new Error("Expected HTTP test fetch init");
    const body = JSON.parse(String(init.body));

    expect(body).toEqual({
      config: makeConfig(),
      direction: "output",
      method: "POST",
      test_variables: { base_url: "https://api.example.com", name: "Alex" }
    });
  });

  it("keeps invalid test variables local and does not call the API", async () => {
    const fetchMock = stubFetch({ success: true });
    renderHttpTestConnection();

    await fireEvent.input(screen.getByLabelText(m.http_test_variables_label()), {
      target: { value: "{bad" }
    });
    await fireEvent.click(screen.getByRole("button", { name: m.http_test_button() }));

    expect(fetchMock).not.toHaveBeenCalled();
    await screen.findByText(m.http_test_variables_invalid());
  });

  it("renders request previews from failed transport responses", async () => {
    stubFetch({
      success: false,
      error_code: "HTTP_INVALID_URL",
      error_message: "Invalid URL format",
      request_preview: {
        method: "POST",
        url: "not-a-url/hook",
        headers: { "X-Test": "case-1" },
        body_preview: "hello Alex"
      }
    });
    renderHttpTestConnection();

    await fireEvent.input(screen.getByLabelText(m.http_test_variables_label()), {
      target: { value: '{"base_url":"not-a-url","name":"Alex"}' }
    });
    await fireEvent.click(screen.getByRole("button", { name: m.http_test_button() }));

    await screen.findByText("Invalid URL format");
    await screen.findByText(m.http_test_request_preview());
    await screen.findByText("POST");
    await screen.findByText("not-a-url/hook");
    await screen.findByText(/"X-Test": "case-1"/);
    await screen.findByText("hello Alex");
  });

  it("handles non-OK API envelopes instead of rendering a generic result", async () => {
    stubFetch({ detail: "Not allowed" }, { ok: false, status: 403, statusText: "Forbidden" });
    renderHttpTestConnection();

    await fireEvent.click(screen.getByRole("button", { name: m.http_test_button() }));

    await screen.findByText("403: Not allowed");
  });
});
