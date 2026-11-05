// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { renderInApp } from "@/test/render";
import { FlowChatPanel } from "./flow-chat-panel";
import { makeFlow } from "./flow-fixtures";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn() }));

vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));

function refuseChat(body: Record<string, unknown>) {
  api.POST.mockResolvedValue({ error: body, response: new Response(null, { status: 400 }) });
}

function renderPanel() {
  return renderInApp(
    <FlowChatPanel
      flow={makeFlow()}
      onFlowMayHaveChanged={() => {}}
      onRefused={() => {}}
      onComposer={() => {}}
    />
  );
}

/** The status of the banner around the given text. */
async function bannerStatus(text: string) {
  const description = await screen.findByText(text);
  return description.closest(".astryx-banner")?.getAttribute("data-status");
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("FlowChatPanel when the chat cannot open", () => {
  it("says in Swedish who declares a model's limits, as a warning", async () => {
    refuseChat({
      message: "Unknown model capacity: max_input_tokens",
      code: "unknown_model_capacity",
      eneo_error_code: 9074
    });
    renderPanel();

    expect(await bannerStatus(messages.flows_chat_model_capacity_unknown)).toBe("warning");
    expect(screen.getByText(messages.flows_chat_unavailable)).toBeTruthy();
    expect(screen.queryByText(/Unknown model capacity/)).toBeNull();
  });

  it("gives a missing model its own text, as information", async () => {
    refuseChat({
      message: "No model.",
      code: "flow_authoring_chat_no_model",
      eneo_error_code: 9007
    });
    renderPanel();

    expect(await bannerStatus(messages.flows_chat_no_model)).toBe("info");
  });

  it("uses the flow catalog's sentence for a refusal it has one for", async () => {
    refuseChat({
      message: "The reasoning effort is not supported.",
      code: "flow_authoring_reasoning_effort_unsupported",
      eneo_error_code: 9007
    });
    renderPanel();

    expect(
      await screen.findByText(messages.flow_error_flow_authoring_reasoning_effort_unsupported)
    ).toBeTruthy();
    expect(screen.queryByText(/not supported/)).toBeNull();
  });

  it("never shows the core's English for a refusal it has no text for", async () => {
    refuseChat({ message: "Something internal went sideways.", code: "brand_new_refusal" });
    renderPanel();

    expect(await screen.findByText(messages.request_failed)).toBeTruthy();
    expect(screen.queryByText(/sideways/)).toBeNull();
  });
});
