import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import { createEneo } from "@eneo/eneo-js";

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => createEneo({ baseUrl: "https://eneo.example", token: "test-user-token" })
}));

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

function renderHttpTestConnection(config = makeConfig(), stepId: string | null = "step-2") {
  return render(HttpTestConnection, {
    props: {
      config,
      direction: "output",
      method: "POST",
      flowId: "flow-1",
      stepId,
      isPublished: false
    }
  });
}

function stubFetch(payload: unknown, options: { status?: number; statusText?: string } = {}) {
  const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => {
    return new Response(JSON.stringify(payload), {
      status: options.status ?? 200,
      statusText: options.statusText ?? "OK",
      headers: { "Content-Type": "application/json" }
    });
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
      stepId: "step-2",
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

  it("sends auth and the selected step after raw fetch is removed", async () => {
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

    // Mutant: bypass the authenticated SDK or omit the selected credential owner.
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer test-user-token");
    expect(body).toEqual({
      step_id: "step-2",
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
    await waitFor(() => {
      expect(screen.getByRole("status").textContent).toContain(m.http_test_variables_invalid());
    });
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

    await screen.findByText(/Invalid URL format/);
    await screen.findByText(m.http_test_request_preview());
    await screen.findByText("POST");
    await screen.findByText("not-a-url/hook");
    await screen.findByText(/"X-Test": "case-1"/);
    await screen.findByText("hello Alex");
  });

  it("maps typed permission errors after bespoke envelope parsing is removed", async () => {
    // Mutant: bypass the SDK error envelope and show its raw message.
    stubFetch(
      {
        code: "flow_owner_required",
        message: "Raw server permission error",
        eneo_error_code: 9006
      },
      { status: 403, statusText: "Forbidden" }
    );
    renderHttpTestConnection();

    await fireEvent.click(screen.getByRole("button", { name: m.http_test_button() }));

    await screen.findByText(new RegExp(m.flow_error_flow_owner_required()));
  });

  it("prevents an unsaved step from testing another step's credentials", async () => {
    // Mutant: omit the saved-step prerequisite and send an ownerless HTTP test.
    const fetchMock = stubFetch({ success: true });
    renderHttpTestConnection(
      makeConfig({ url: "https://api.example.com", body: { mode: "none" } }),
      null
    );

    const button = screen.getByRole("button", { name: m.http_test_button() });
    expect(button.hasAttribute("disabled")).toBe(true);
    expect(screen.getByText(m.http_test_saved_step_required())).toBeTruthy();
    await fireEvent.click(button);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("announces the result in a live status region", async () => {
    stubFetch({ success: true, status_code: 200, duration_ms: 42 });
    renderHttpTestConnection(
      makeConfig({ url: "https://api.example.com/hook", body: { mode: "none" } })
    );

    const status = screen.getByRole("status");
    expect(status.textContent?.trim()).toBe("");

    await fireEvent.click(screen.getByRole("button", { name: m.http_test_button() }));

    await waitFor(() => {
      expect(status.textContent).toContain(m.http_test_success());
      expect(status.textContent).toContain("200");
    });
  });

  it("announces failures with the failed prefix, never color alone", async () => {
    stubFetch({ success: false, error_message: "boom" });
    renderHttpTestConnection(
      makeConfig({ url: "https://api.example.com/hook", body: { mode: "none" } })
    );

    await fireEvent.click(screen.getByRole("button", { name: m.http_test_button() }));

    await waitFor(() => {
      expect(screen.getByRole("status").textContent).toContain(
        `${m.http_test_failed_prefix()}: boom`
      );
    });
  });
});
