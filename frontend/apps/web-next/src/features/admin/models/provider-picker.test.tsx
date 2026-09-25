// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeAll, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import type { ProviderOption } from "./model-providers";
import { ProviderPicker } from "./provider-picker";

const options: ProviderOption[] = [
  { type: "openai", name: "OpenAI", modes: ["completion", "embedding"], selfHosted: false },
  { type: "anthropic", name: "Anthropic", modes: ["completion"], selfHosted: false },
  {
    type: "hosted_vllm",
    name: "vLLM",
    modes: ["completion", "embedding", "transcription"],
    selfHosted: true
  }
];

beforeAll(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
  );
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {}
  }));
});

afterEach(cleanup);

function renderPicker(favorites = new Set(["anthropic"])) {
  const onSelect = vi.fn();
  const onToggleFavorite = vi.fn();
  render(
    <NextIntlClientProvider locale="sv" messages={messages}>
      <ProviderPicker
        options={options}
        favorites={favorites}
        onSelect={onSelect}
        onToggleFavorite={onToggleFavorite}
      />
    </NextIntlClientProvider>
  );
  return { onSelect, onToggleFavorite };
}

it("lists favourites first and pins with a toggle that keeps its name", async () => {
  const { onSelect, onToggleFavorite } = renderPicker();

  const pinned = screen.getByRole("button", { name: "Fäst Anthropic som favorit" });
  expect(pinned.getAttribute("aria-pressed")).toBe("true");
  const unpinned = screen.getByRole("button", { name: "Fäst OpenAI som favorit" });
  expect(unpinned.getAttribute("aria-pressed")).toBe("false");

  fireEvent.click(unpinned);
  expect(onToggleFavorite).toHaveBeenCalledWith("openai");

  fireEvent.click(screen.getByRole("button", { name: "Lägg till vLLM" }));
  expect(onSelect).toHaveBeenCalledWith("hosted_vllm");

  await expectNoAxeViolations(document.body);
});

it("filters by capability, self-hosting and search", () => {
  renderPicker(new Set());
  const capabilities = screen.getByRole("radiogroup", { name: "Kapaciteter" });

  fireEvent.click(within(capabilities).getByRole("radio", { name: "Tal-till-text" }));
  expect(screen.queryByRole("button", { name: "Lägg till OpenAI" })).toBeNull();
  expect(screen.getByRole("button", { name: "Lägg till vLLM" })).toBeTruthy();

  fireEvent.click(within(capabilities).getByRole("radio", { name: "Alla providers" }));
  const selfHosted = screen.getByRole("button", { name: "Självhostad" });
  fireEvent.click(selfHosted);
  expect(selfHosted.getAttribute("aria-pressed")).toBe("true");
  expect(screen.queryByRole("button", { name: "Lägg till Anthropic" })).toBeNull();

  fireEvent.click(selfHosted);
  fireEvent.change(screen.getByRole("textbox", { name: "Sök providers" }), {
    target: { value: "anthro" }
  });
  expect(screen.getByRole("button", { name: "Lägg till Anthropic" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Lägg till OpenAI" })).toBeNull();
});
