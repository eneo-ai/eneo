// @vitest-environment jsdom
import { QueryClient, QueryClientProvider, useMutation } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Assistant } from "./use-assistant";

const update = vi.hoisted(() => vi.fn().mockResolvedValue({}));
// The section's own mutation, saving through `update`.
vi.mock("./use-assistant", () => ({
  useUpdateAssistant: () => useMutation({ mutationFn: (body: unknown) => update(body) })
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
  update.mockReset();
  update.mockResolvedValue({});
});

function show(value: Assistant) {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <CapabilitiesSection assistant={value} />
    </QueryClientProvider>
  );
}

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
    show(assistant(["image_generation"], true));
    fireEvent.click(screen.getByRole("switch", { name: "web_search" }));
    await waitFor(() =>
      expect(update).toHaveBeenCalledWith({
        enabled_capabilities: ["image_generation", "web_search"]
      })
    );
  });

  it("lets editors disable a function whose provider became unavailable", async () => {
    show(assistant(["web_search"], false));
    const web = screen.getByRole("switch", { name: "web_search" });
    const image = screen.getByRole("switch", { name: "image_generation" });
    expect(web.hasAttribute("disabled")).toBe(false);
    expect(image.hasAttribute("disabled")).toBe(true);
    fireEvent.click(web);
    await waitFor(() => expect(update).toHaveBeenCalledWith({ enabled_capabilities: [] }));
  });

  it("keeps focus on a switch while it saves, and ignores a toggle meanwhile", async () => {
    update.mockReturnValue(new Promise(() => {}));
    show(assistant([], true));
    const web = screen.getByRole("switch", { name: "web_search" });
    web.focus();

    fireEvent.click(web);

    await waitFor(() => expect(web.getAttribute("aria-busy")).toBe("true"));
    expect(web.hasAttribute("disabled")).toBe(false);
    expect(document.activeElement).toBe(web);
    // Only the switch being saved says so.
    expect(
      screen.getByRole("switch", { name: "image_generation" }).getAttribute("aria-busy")
    ).toBeNull();
    fireEvent.click(web);
    fireEvent.click(screen.getByRole("switch", { name: "image_generation" }));
    expect(update).toHaveBeenCalledTimes(1);
  });
});
