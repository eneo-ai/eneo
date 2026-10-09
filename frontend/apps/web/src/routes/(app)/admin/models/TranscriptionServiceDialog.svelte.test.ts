import type { TranscriptionService } from "@eneo/eneo-js";
import { EneoError } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, expect, it, vi } from "vitest";

import TranscriptionServiceDialog from "./TranscriptionServiceDialog.svelte";
import { m } from "$lib/paraglide/messages";

const classification = { id: "c1", name: "Intern", description: null, security_level: 2 };

const saved: TranscriptionService = {
  id: "s1",
  name: "Vemsa Sundsvall",
  endpoint_url: "https://vemsa.sundsvall.se",
  is_enabled: true,
  security_classification: null,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z"
};

const create = vi.fn();
const update = vi.fn();

const props = (service: TranscriptionService | null) => ({
  open: true,
  service,
  classifications: [classification],
  onCreate: create,
  onUpdate: update,
  onTest: vi.fn()
});

beforeEach(() => {
  create.mockReset().mockResolvedValue(undefined);
  update.mockReset().mockResolvedValue(undefined);
});

it("connects a service with the entered settings, on by default", async () => {
  render(TranscriptionServiceDialog, props(null));

  await page.getByLabelText(m.name()).fill("Vemsa Sundsvall");
  await page.getByLabelText(m.speaker_service_address()).fill("https://vemsa.sundsvall.se");
  await page.getByLabelText(m.speaker_service_api_key()).fill("secret-key");
  await page.getByRole("button", { name: m.speaker_service_connect_submit() }).click();

  await expect.poll(() => create.mock.calls.length).toBe(1);
  expect(create).toHaveBeenCalledWith({
    name: "Vemsa Sundsvall",
    endpoint_url: "https://vemsa.sundsvall.se",
    api_key: "secret-key",
    is_enabled: true,
    security_classification: null
  });
  await expect.element(page.getByRole("dialog")).not.toBeInTheDocument();
});

it("asks for a new key before saving a moved address", async () => {
  render(TranscriptionServiceDialog, props(saved));

  const address = page.getByLabelText(m.speaker_service_address());
  await address.fill("https://vemsa2.sundsvall.se");
  await expect.element(page.getByText(m.speaker_service_api_key_new_address())).toBeVisible();

  await page.getByRole("button", { name: m.save() }).click();
  expect(update).not.toHaveBeenCalled();
  await expect
    .element(page.getByLabelText(m.speaker_service_api_key()))
    .toHaveAttribute("aria-invalid", "true");
});

it("keeps the entered values and points at the name when it is taken", async () => {
  create.mockRejectedValue(new EneoError("Name taken", "SERVER", 409, 9017));
  render(TranscriptionServiceDialog, props(null));

  await page.getByLabelText(m.name()).fill("Vemsa Sundsvall");
  await page.getByLabelText(m.speaker_service_address()).fill("https://vemsa.sundsvall.se");
  await page.getByLabelText(m.speaker_service_api_key()).fill("secret-key");
  await page.getByRole("button", { name: m.speaker_service_connect_submit() }).click();

  await expect.element(page.getByText(m.speaker_service_name_taken())).toBeVisible();
  await expect.element(page.getByLabelText(m.name())).toHaveValue("Vemsa Sundsvall");
  await expect
    .element(page.getByLabelText(m.speaker_service_address()))
    .toHaveValue("https://vemsa.sundsvall.se");
  await expect.element(page.getByLabelText(m.speaker_service_api_key())).toHaveValue("secret-key");
  await expect.element(page.getByRole("dialog")).toBeVisible();
});

it("explains a refused address in the user's language", async () => {
  create.mockRejectedValue(
    new EneoError("Invalid", "SERVER", 422, 9000, {
      details: {
        errors: [
          {
            location: ["body", "endpoint_url"],
            type: "service_endpoint_credentials",
            message: "The endpoint must not contain credentials; enter the API key separately."
          }
        ]
      }
    })
  );
  render(TranscriptionServiceDialog, props(null));

  await page.getByLabelText(m.name()).fill("Vemsa Sundsvall");
  await page.getByLabelText(m.speaker_service_address()).fill("https://user:pw@vemsa.sundsvall.se");
  await page.getByLabelText(m.speaker_service_api_key()).fill("secret-key");
  await page.getByRole("button", { name: m.speaker_service_connect_submit() }).click();

  await expect.element(page.getByText(m.speaker_service_endpoint_credentials())).toBeVisible();
});

it("sends only what the administrator changed", async () => {
  // With enforcement off the API reads a stored classification as null; a
  // rename that echoed it back would clear it.
  render(TranscriptionServiceDialog, props(saved));

  await page.getByLabelText(m.name()).fill("Vemsa Sundsvall Nord");
  await page.getByRole("button", { name: m.save() }).click();

  await expect.poll(() => update.mock.calls.length).toBe(1);
  expect(update).toHaveBeenCalledWith("s1", { name: "Vemsa Sundsvall Nord" });
});

it("treats a trailing slash or /v1 as the saved address", async () => {
  render(TranscriptionServiceDialog, props(saved));

  const address = page.getByLabelText(m.speaker_service_address());
  for (const same of ["https://vemsa.sundsvall.se/", "https://vemsa.sundsvall.se/v1/"]) {
    await address.fill(same);
    await expect
      .element(page.getByText(m.speaker_service_api_key_new_address()))
      .not.toBeInTheDocument();
  }

  await page.getByRole("button", { name: m.save() }).click();
  await expect.poll(() => update.mock.calls.length).toBe(1);
  expect(update).toHaveBeenCalledWith("s1", {});
});
