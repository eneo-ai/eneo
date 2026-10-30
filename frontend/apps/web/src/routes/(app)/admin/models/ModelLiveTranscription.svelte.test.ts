import type { TranscriptionModel } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { writable } from "svelte/store";
import { beforeEach, expect, it, vi } from "vitest";

const { updateTranscription } = vi.hoisted(() => ({
  updateTranscription: vi.fn(async (_identifier: { id: string }, _payload: unknown) => ({}))
}));
vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({ tenantModels: { updateTranscription } })
}));
vi.mock("$app/navigation", () => ({ invalidate: vi.fn() }));
vi.mock("$lib/features/security-classifications/SecurityContext", () => ({
  getSecurityContext: () => ({ security_classifications: [] })
}));

import EditModelDialog from "./EditModelDialog.svelte";
import ModelDetailDialog from "./ModelDetailDialog.svelte";
import ModelStatusIcons from "$lib/features/ai-models/components/ModelStatusIcons.svelte";
import { setLocale } from "$lib/paraglide/runtime";
import { m } from "$lib/paraglide/messages";

function model(providerType: string | null, supportsRealtime = false): TranscriptionModel {
  return {
    id: "t1",
    name: "pianissimo-sv",
    nickname: "Pianissimo",
    hosting: "swe",
    is_deprecated: false,
    cost_per_minute: null,
    provider_id: "p1",
    provider_type: providerType,
    supports_realtime: supportsRealtime
  };
}

function editLiveTranscription(providerType: string | null) {
  render(EditModelDialog, {
    openController: writable(true),
    model: model(providerType),
    type: "transcriptionModel"
  });
  return page.getByRole("checkbox", { name: new RegExp(m.live_transcription_support()) });
}

beforeEach(() => {
  updateTranscription.mockClear();
  setLocale("sv", { reload: false });
});

// "vllm" is the backend's alias for hosted_vllm, and a provider created through
// the API keeps the type it was given.
it.each(["hosted_vllm", "vllm"])(
  "turns live transcription on for a %s provider",
  async (providerType) => {
    const toggle = editLiveTranscription(providerType);
    await expect.element(toggle).toBeEnabled();
    await expect.element(page.getByText(m.live_transcription_needs_vllm())).not.toBeInTheDocument();

    await toggle.click();
    await expect.element(toggle).toBeChecked();
    await page.getByRole("button", { name: m.save(), exact: true }).click();

    await expect.poll(() => updateTranscription.mock.calls.length).toBe(1);
    expect(updateTranscription.mock.calls[0][1]).toMatchObject({ supports_realtime: true });
  }
);

it.each(["openai", null])(
  "says why live transcription is unavailable for provider type %s",
  async (providerType) => {
    const toggle = editLiveTranscription(providerType);
    await expect.element(toggle).toBeDisabled();
    await expect.element(page.getByText(m.live_transcription_needs_vllm())).toBeVisible();
    await expect.element(toggle).toHaveAccessibleDescription(m.live_transcription_needs_vllm());
  }
);

it.each([
  [true, "yes"],
  [false, "no"]
] as const)("states live transcription %s in the model details", async (supported, answer) => {
  render(ModelDetailDialog, {
    openController: writable(true),
    model: model("hosted_vllm", supported),
    type: "transcriptionModel"
  });
  await expect
    .element(
      page.getByRole("row", {
        name: `${m.live_transcription_support()} ${answer === "yes" ? m.yes() : m.no()}`,
        exact: true
      })
    )
    .toBeVisible();
});

it.each([true, false])("marks live transcription in the model table: %s", async (supported) => {
  render(ModelStatusIcons, { model: model("hosted_vllm", supported) });
  await expect.element(page.getByRole("list")).toBeInTheDocument();
  const marker = page.getByRole("listitem", { name: m.live_transcription_support(), exact: true });
  if (supported) await expect.element(marker).toBeVisible();
  else await expect.element(marker).not.toBeInTheDocument();
});
