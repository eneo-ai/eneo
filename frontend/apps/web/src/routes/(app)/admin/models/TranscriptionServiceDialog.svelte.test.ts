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
  space_count: 0,
  last_check: null,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z"
};

const create = vi.fn();
const update = vi.fn();

const props = (service: TranscriptionService | null) => ({
  open: true,
  service,
  classifications: [classification],
  checking: false,
  onCreate: create,
  onUpdate: update,
  onTest: vi.fn()
});

// The dialog moves focus to its first field just after it opens; typing
// elsewhere before that settles would land in the name field.
async function openDialog(dialogProps: ReturnType<typeof props>) {
  const view = render(TranscriptionServiceDialog, dialogProps);
  await expect.element(page.getByLabelText(m.name())).toHaveFocus();
  return view;
}

beforeEach(() => {
  create.mockReset().mockResolvedValue(saved);
  update.mockReset().mockResolvedValue(saved);
});

it("connects a service with the entered settings, on by default, and stays open on it", async () => {
  await openDialog(props(null));

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
  await expect
    .element(
      page.getByRole("heading", {
        name: m.speaker_service_dialog_connected_title({ name: "Vemsa Sundsvall" })
      })
    )
    .toBeVisible();
  // The key is saved; the field now offers to replace it.
  await expect.element(page.getByLabelText(m.speaker_service_api_key())).toHaveValue("");
  // Everything is saved, so the only way out is "Klar", and it has the focus.
  await expect.element(page.getByRole("button", { name: m.done() })).toHaveFocus();
  await expect.element(page.getByRole("button", { name: m.save() })).not.toBeInTheDocument();
});

it("shows the new service's test and lets a refused key be fixed in place", async () => {
  const { rerender } = await openDialog(props(null));
  await page.getByLabelText(m.name()).fill("Vemsa Sundsvall");
  await page.getByLabelText(m.speaker_service_address()).fill("https://vemsa.sundsvall.se");
  await page.getByLabelText(m.speaker_service_api_key()).fill("wrong-key");
  await page.getByRole("button", { name: m.speaker_service_connect_submit() }).click();
  await expect.poll(() => create.mock.calls.length).toBe(1);

  await rerender({ ...props(null), checking: true });
  await expect.element(page.getByText(m.speaker_service_testing_connection())).toBeVisible();
  await rerender({
    ...props(null),
    check: {
      outcome: "credentials_rejected",
      identifies_speakers: null,
      service_version: null,
      checked_at: "2026-10-09T07:00:00Z"
    }
  });
  await expect.element(page.getByText(m.speaker_service_status_credentials())).toBeVisible();

  await page.getByLabelText(m.speaker_service_api_key()).fill("right-key");
  await page.getByRole("button", { name: m.save() }).click();

  await expect.poll(() => update.mock.calls.length).toBe(1);
  expect(update).toHaveBeenCalledWith("s1", { api_key: "right-key" });
  await expect.element(page.getByRole("dialog")).toBeVisible();
});

it("asks for a new key before saving a moved address", async () => {
  await openDialog(props(saved));

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
  await openDialog(props(null));

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
  await openDialog(props(null));

  await page.getByLabelText(m.name()).fill("Vemsa Sundsvall");
  await page.getByLabelText(m.speaker_service_address()).fill("https://user:pw@vemsa.sundsvall.se");
  await page.getByLabelText(m.speaker_service_api_key()).fill("secret-key");
  await page.getByRole("button", { name: m.speaker_service_connect_submit() }).click();

  await expect.element(page.getByText(m.speaker_service_endpoint_credentials())).toBeVisible();
});

it("sends only what the administrator changed", async () => {
  // With enforcement off the API reads a stored classification as null; a
  // rename that echoed it back would clear it.
  await openDialog(props(saved));

  await page.getByLabelText(m.name()).fill("Vemsa Sundsvall Nord");
  await page.getByRole("button", { name: m.save() }).click();

  await expect.poll(() => update.mock.calls.length).toBe(1);
  expect(update).toHaveBeenCalledWith("s1", { name: "Vemsa Sundsvall Nord" });
});

it("treats a trailing slash or /v1 as the saved address", async () => {
  await openDialog(props(saved));

  const address = page.getByLabelText(m.speaker_service_address());
  for (const same of ["https://vemsa.sundsvall.se/", "https://vemsa.sundsvall.se/v1/"]) {
    await address.fill(same);
    await expect
      .element(page.getByText(m.speaker_service_api_key_new_address()))
      .not.toBeInTheDocument();
  }

  // Nothing changed, so there is nothing to save.
  await expect.element(page.getByRole("button", { name: m.save() })).not.toBeInTheDocument();
  await page.getByRole("button", { name: m.done() }).click();
  await expect.element(page.getByRole("dialog")).not.toBeInTheDocument();
  expect(update).not.toHaveBeenCalled();
});

it("locks the fields while a save is answering, so nothing typed meanwhile is lost", async () => {
  let answer = (_service: TranscriptionService) => {};
  create.mockReturnValueOnce(new Promise((resolve) => (answer = resolve)));
  await openDialog(props(null));

  await page.getByLabelText(m.name()).fill("Vemsa Sundsvall");
  await page.getByLabelText(m.speaker_service_address()).fill("https://vemsa.sundsvall.se");
  await page.getByLabelText(m.speaker_service_api_key()).fill("secret-key");
  await page.getByRole("button", { name: m.speaker_service_connect_submit() }).click();

  await expect.element(page.getByLabelText(m.speaker_service_api_key())).toBeDisabled();
  await expect.element(page.getByLabelText(m.name())).toBeDisabled();
  answer(saved);
  await expect.element(page.getByLabelText(m.speaker_service_api_key())).toBeEnabled();
});

it("counts a saved classification as saved even when the service reads it back as none", async () => {
  // With classification enforcement off the API reads every classification as none.
  const onTest = vi.fn();
  await openDialog({ ...props(null), onTest });

  await page.getByLabelText(m.name()).fill("Vemsa Sundsvall");
  await page.getByLabelText(m.speaker_service_address()).fill("https://vemsa.sundsvall.se");
  await page.getByLabelText(m.speaker_service_api_key()).fill("secret-key");
  await page.getByLabelText(m.speaker_service_column_classification()).click();
  await page.getByRole("option", { name: "Intern" }).click();
  await page.getByRole("button", { name: m.speaker_service_connect_submit() }).click();
  await expect.poll(() => create.mock.calls.length).toBe(1);

  await expect.element(page.getByRole("button", { name: m.done() })).toBeVisible();
  await page.getByRole("button", { name: m.speaker_service_test() }).click();
  expect(onTest).toHaveBeenCalledOnce();
  await expect.element(page.getByText(m.speaker_service_save_first())).not.toBeInTheDocument();
});
