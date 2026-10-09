import type { TranscriptionServiceSummary } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { get, writable, type Writable } from "svelte/store";
import { beforeEach, expect, it, vi } from "vitest";

const { currentSpace, updateSpace } = vi.hoisted(() => ({
  currentSpace: { value: null as unknown, store: null as unknown },
  updateSpace: vi.fn(async (_patch: unknown) => {})
}));
vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({
    state: { currentSpace: (currentSpace.store = writable(currentSpace.value)) },
    updateSpace
  })
}));

import SelectSpaceSpeakerServices from "./SelectSpaceSpeakerServices.svelte";
import { m } from "$lib/paraglide/messages";

const restricted = { id: "c2", name: "Skyddad", description: null, security_level: 3 };

const service = (
  id: string,
  name: string,
  overrides: Partial<TranscriptionServiceSummary> = {}
): TranscriptionServiceSummary => ({
  id,
  name,
  is_enabled: true,
  security_classification: null,
  ...overrides
});

const link = (id: string, name: string, meets = true, available = true) => ({
  id,
  name,
  meets_security_classification: meets,
  available
});

// The selector hands the manager a function of the space as it stands when the
// update starts; this is the patch it builds from the current store.
function sentPatch(call: number) {
  const update = updateSpace.mock.calls[call][0];
  return typeof update === "function"
    ? update(get(currentSpace.store as Writable<unknown>))
    : update;
}

beforeEach(() => {
  updateSpace.mockReset();
  updateSpace.mockImplementation(async (_patch: unknown) => {});
});

it("explains why a granted service cannot be used, and keeps it removable", async () => {
  currentSpace.value = {
    security_classification: restricted,
    transcription_services: [
      link("low", "Vemsa Sundsvall", false, true),
      link("off", "Vemsa Timrå", true, false)
    ]
  };
  render(SelectSpaceSpeakerServices, {
    services: [
      service("low", "Vemsa Sundsvall"),
      service("off", "Vemsa Timrå", { is_enabled: false, security_classification: restricted })
    ],
    securityEnabled: true
  });

  await expect.element(page.getByText(m.speaker_service_reason_classification())).toBeVisible();
  await expect.element(page.getByText(m.speaker_service_reason_disabled())).toBeVisible();
  const low = page.getByRole("switch", { name: "Vemsa Sundsvall" });
  await expect.element(low).toBeChecked();
  await expect.element(low).toBeEnabled();
});

it("grants a usable service and refuses one below the space's classification", async () => {
  currentSpace.value = {
    security_classification: restricted,
    transcription_services: [link("kept", "Vemsa Härnösand")]
  };
  render(SelectSpaceSpeakerServices, {
    services: [
      service("kept", "Vemsa Härnösand", { security_classification: restricted }),
      service("low", "Vemsa Sundsvall"),
      service("new", "Vemsa Timrå", { security_classification: restricted })
    ],
    securityEnabled: true
  });

  await expect.element(page.getByRole("switch", { name: "Vemsa Sundsvall" })).toBeDisabled();
  await page.getByRole("switch", { name: "Vemsa Timrå" }).click();
  await expect.poll(() => updateSpace.mock.calls.length).toBe(1);
  expect(sentPatch(0)).toEqual({ transcription_services: [{ id: "kept" }, { id: "new" }] });
});

it("shows the grant as it was when the save fails", async () => {
  currentSpace.value = { security_classification: null, transcription_services: [] };
  updateSpace.mockRejectedValueOnce(new Error("offline"));
  render(SelectSpaceSpeakerServices, {
    services: [service("s1", "Vemsa Sundsvall")],
    securityEnabled: false
  });

  const toggle = page.getByRole("switch", { name: "Vemsa Sundsvall" });
  await toggle.click();
  await expect.poll(() => updateSpace.mock.calls.length).toBe(1);

  await expect.element(toggle).toBeEnabled();
  await expect.element(toggle).not.toBeChecked();
});

it("says so when the organisation's services could not be read", async () => {
  currentSpace.value = { security_classification: null, transcription_services: [] };
  render(SelectSpaceSpeakerServices, { services: null, securityEnabled: false });

  await expect
    .element(page.getByRole("alert"))
    .toHaveTextContent(m.speaker_service_space_load_failed());
  await expect.element(page.getByRole("switch")).not.toBeInTheDocument();
});
