// @vitest-environment jsdom
import { screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { renderInApp } from "@/test/render";
import messages from "@/lib/i18n/messages/sv.json";
import { EMPTY_POLICY } from "./policy-draft";
import { McpRestrictionSection } from "./mcp-restriction-section";
import { ReasoningPolicySection } from "./reasoning-policy-section";
import { usePolicyDraft, type PolicyDraftInput } from "./use-policy-draft";

const general = { id: "general", name: "General server", is_available: true };
const search = {
  id: "search-one",
  name: "Search one",
  purpose: "web_search" as const,
  is_available: true,
  is_enabled: true
};
const input: PolicyDraftInput = {
  policy: EMPTY_POLICY,
  models: [],
  providers: [],
  servers: [],
  prompts: [],
  selectiveActivationEnabled: false
};

function McpPolicy({ value }: { value: PolicyDraftInput }) {
  return <McpRestrictionSection draft={usePolicyDraft(value)} />;
}

function ReasoningPolicy({ value }: { value: PolicyDraftInput }) {
  return <ReasoningPolicySection draft={usePolicyDraft(value)} />;
}

it.each([true, false])(
  "counts the actual MCP rows after a source refresh (capability selected: %s)",
  (selectedCapability) => {
    const value: PolicyDraftInput = {
      ...input,
      servers: [general, search, { ...search, id: "search-two" }],
      policy: {
        ...EMPTY_POLICY,
        mcp_restriction: {
          enabled: true,
          servers: [{ mcp_server_id: general.id, is_default_enabled: true }],
          disabled_tool_ids: [],
          capabilities: selectedCapability
            ? [{ purpose: "web_search", is_default_enabled: true }]
            : []
        }
      }
    };
    const { rerender } = renderInApp(<McpPolicy value={value} />);
    const section = screen.getByRole("region", { name: messages.governance_mcp_heading });
    const rows = () =>
      within(section)
        .getAllByRole("group")
        .flatMap((group) => within(group).getAllByRole("switch", { name: /^Tillåt / }));
    const selected = () =>
      rows().filter((row) => row.getAttribute("aria-checked") === "true").length;
    expect(
      within(section).getAllByRole("switch", { name: `Tillåt ${messages.web_search}` })
    ).toHaveLength(1);
    expect(within(section).getByText(`Aktiv – ${selected()} av ${rows().length}`)).toBeTruthy();

    // Sources can change without replacing the policy or discarding the draft.
    rerender(<McpPolicy value={{ ...value, servers: [] }} />);
    expect(within(section).queryByRole("switch", { name: "Tillåt General server" })).toBeNull();
    expect(selected()).toBe(selectedCapability ? 1 : 0);
    expect(
      within(section).getByText(
        selectedCapability
          ? `Aktiv – ${selected()} av ${rows().length}`
          : messages.governance_mcp_summary_none
      )
    ).toBeTruthy();
  }
);

it.each([
  [true, "Hög · användare kan ändra"],
  [false, "Hög · styrs av organisationen"]
] as const)(
  "uses the dropdown's localized reasoning label (user override: %s)",
  (allowOverride, summary) => {
    renderInApp(
      <ReasoningPolicy
        value={{
          ...input,
          models: [
            {
              id: "model",
              name: "Model",
              can_access: true,
              supported_model_kwargs: {
                reasoning_effort: { supported: true, control: "select", options: ["low", "high"] }
              }
            }
          ],
          policy: {
            ...EMPTY_POLICY,
            reasoning_policy: {
              configured: true,
              default_effort: "high",
              allow_user_override: allowOverride
            }
          }
        }}
      />
    );
    const section = screen.getByRole("region", { name: messages.governance_reasoning_heading });
    expect(within(section).getByRole("combobox").textContent).toBe("Hög");
    expect(within(section).getByText(summary)).toBeTruthy();
  }
);
