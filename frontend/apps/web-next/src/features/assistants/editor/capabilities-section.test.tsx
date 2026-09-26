// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Assistant } from "./use-assistant";

const update = vi.hoisted(() => vi.fn().mockResolvedValue({}));
vi.mock("./use-assistant", () => ({
  useUpdateAssistant: () => ({ mutateAsync: update, isPending: false })
}));
vi.mock("@/features/spaces/use-space", () => ({
  useSpace: () => ({ space: { enabled_capabilities: ["web_search", "image_generation"] } })
}));
vi.mock("@/components/composites/use-autosave", () => ({
  useAutosave: () => (operation: () => Promise<unknown>) => operation()
}));
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

import { CapabilitiesSection } from "./capabilities-section";

afterEach(() => {
  cleanup();
  update.mockClear();
});

const assistant = (enabled: ("web_search" | "image_generation")[], available: boolean) =>
  ({
    id: "assistant",
    permissions: ["edit"],
    enabled_capabilities: enabled,
    available_capabilities: [
      { purpose: "web_search", available },
      { purpose: "image_generation", available }
    ],
    completion_model: { supports_tool_calling: true }
  }) as Assistant;

describe("assistant capabilities", () => {
  it("saves the complete selection when enabling a function", async () => {
    render(<CapabilitiesSection assistant={assistant(["image_generation"], true)} />);
    fireEvent.click(screen.getByRole("switch", { name: "web_search" }));
    await waitFor(() =>
      expect(update).toHaveBeenCalledWith({
        enabled_capabilities: ["image_generation", "web_search"]
      })
    );
  });

  it("lets editors disable a function whose provider became unavailable", async () => {
    render(<CapabilitiesSection assistant={assistant(["web_search"], false)} />);
    const web = screen.getByRole("switch", { name: "web_search" });
    const image = screen.getByRole("switch", { name: "image_generation" });
    expect(web.hasAttribute("disabled")).toBe(false);
    expect(image.hasAttribute("disabled")).toBe(true);
    fireEvent.click(web);
    await waitFor(() => expect(update).toHaveBeenCalledWith({ enabled_capabilities: [] }));
  });
});
