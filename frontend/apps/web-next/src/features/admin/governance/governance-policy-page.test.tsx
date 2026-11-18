// @vitest-environment jsdom
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AppContextProvider } from "@/components/providers/app-context";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";
import { expectNoAxeViolations } from "@/test/axe";
import { MODELS_KEY } from "@/features/admin/models/models";
import { MCP_KEY } from "@/features/admin/mcp/mcp";
import { PROMPT_LIBRARY_KEY } from "@/features/admin/prompt-library/prompt-library";
import messages from "@/lib/i18n/messages/sv.json";
import {
  GOVERNANCE_POLICY_KEY,
  MODEL_PROVIDERS_KEY,
  SKILL_RUNTIME_POLICY_KEY,
  type GovernancePolicy
} from "./governance";
import { EMPTY_POLICY } from "./policy-draft";
import { GovernancePolicyPage } from "./governance-policy-page";

const api = vi.hoisted(() => ({ GET: vi.fn(), PUT: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/features/skills/skill-bindings-section", () => ({ SkillBindingsEditor: () => null }));
afterEach(() => vi.clearAllMocks());
const ok = (data: unknown) => Promise.resolve({ data, response: new Response() });

function PolicyPage({ filesEnabled }: { filesEnabled: boolean }) {
  return (
    <AppContextProvider
      value={testAppContext({ settings: { file_references_enabled: filesEnabled } })}
    >
      <GovernancePolicyPage />
    </AppContextProvider>
  );
}

function show(filesEnabled: boolean) {
  let saved: GovernancePolicy = {
    ...EMPTY_POLICY,
    file_policy: { configured: true, inline_file_text: false },
    reasoning_policy: { configured: true, default_effort: null, allow_user_override: false }
  };
  api.GET.mockImplementation(() => ok(saved));
  api.PUT.mockImplementation(() => {
    saved = {
      ...saved,
      reasoning_policy: { configured: true, default_effort: null, allow_user_override: true }
    };
    return ok(saved);
  });
  const queryClient = testQueryClient();
  queryClient.setQueryData(GOVERNANCE_POLICY_KEY, saved);
  queryClient.setQueryData(MODELS_KEY, {
    completion_models: [],
    embedding_models: [],
    transcription_models: [],
    image_models: [],
    rerank_models: []
  });
  queryClient.setQueryData(MODEL_PROVIDERS_KEY, []);
  queryClient.setQueryData(MCP_KEY, []);
  queryClient.setQueryData(PROMPT_LIBRARY_KEY, []);
  queryClient.setQueryData(SKILL_RUNTIME_POLICY_KEY, { selective_activation_enabled: false });
  return renderInApp(<PolicyPage filesEnabled={filesEnabled} />, { queryClient });
}

it("hides disabled file policy while preserving its stored value through a failed save and retry elsewhere", async () => {
  const { rerender } = show(false);
  expect(screen.queryByRole("region", { name: messages.governance_files_heading })).toBeNull();
  const reasoning = screen.getByRole("switch", {
    name: messages.governance_reasoning_user_override_label
  });
  fireEvent.click(reasoning);
  api.PUT.mockRejectedValueOnce(new Error("Unavailable"));
  fireEvent.click(screen.getByRole("button", { name: messages.governance_save_changes }));
  expect(await screen.findByText(messages.governance_save_error)).toBeTruthy();
  expect(reasoning.getAttribute("aria-checked")).toBe("true");
  expect(api.PUT).toHaveBeenCalledWith("/api/v1/admin/governance-policy/", {
    body: { reasoning_policy: { default_effort: null, allow_user_override: true } }
  });
  fireEvent.click(screen.getByRole("button", { name: messages.governance_save_changes }));
  await waitFor(() =>
    expect(
      screen.queryByRole("region", { name: messages.governance_unsaved_changes_aria })
    ).toBeNull()
  );
  rerender(<PolicyPage filesEnabled />);
  expect(
    screen
      .getByRole("switch", { name: messages.attachments_open_files_label })
      .getAttribute("aria-checked")
  ).toBe("true");
});

it("shows enabled file references with the On, Off and Example explanation beside the switch", async () => {
  const { container } = show(true);
  const toggle = screen.getByRole("switch", { name: messages.attachments_open_files_label });
  expect(toggle.getAttribute("aria-describedby")).toBe("files-large-help");
  const help = document.getElementById("files-large-help");
  for (const text of [
    messages.attachments_open_files_on,
    messages.attachments_open_files_off,
    messages.attachments_open_files_example
  ])
    expect(help?.textContent).toContain(text);
  await expectNoAxeViolations(container);
});
