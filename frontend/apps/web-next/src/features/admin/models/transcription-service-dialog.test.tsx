// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { EneoApiError } from "@/lib/api/errors";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { TranscriptionServiceDialog } from "./transcription-service-dialog";
import type { TranscriptionService } from "./transcription-services";

const classification = { id: "c1", name: "Intern", description: null, security_level: 2 };

const saved: TranscriptionService = {
  id: "s1",
  name: "Vemsa Sundsvall",
  endpoint_url: "https://vemsa.sundsvall.se",
  is_enabled: true,
  is_default: false,
  security_classification: null,
  space_count: 0,
  last_check: null,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z"
};

const create = vi.fn();
const update = vi.fn();
const onOpenChange = vi.fn();

type Props = Parameters<typeof TranscriptionServiceDialog>[0];

const props = (service: TranscriptionService | null, extra: Partial<Props> = {}): Props => ({
  open: true,
  onOpenChange,
  service,
  classifications: [classification],
  checking: false,
  onCreate: create,
  onUpdate: update,
  onTest: vi.fn(),
  ...extra
});

const field = (name: RegExp) => screen.getByLabelText(name) as HTMLInputElement;
const type = (name: RegExp, value: string) => fireEvent.change(field(name), { target: { value } });
const NAME = /^Namn/;
const ADDRESS = /^Adress/;
const KEY = /^API-nyckel/;

function renderDialog(dialogProps: Props) {
  const view = renderInApp(<TranscriptionServiceDialog {...dialogProps} />);
  return {
    dialog: screen.getByRole("dialog"),
    rerender: (next: Props) => view.rerender(<TranscriptionServiceDialog {...next} />)
  };
}

function fillNew(key = "secret-key") {
  type(NAME, "Vemsa Sundsvall");
  type(ADDRESS, "https://vemsa.sundsvall.se");
  type(KEY, key);
}

const button = (name: string) => screen.getByRole("button", { name });

beforeEach(() => {
  create.mockReset().mockResolvedValue(saved);
  update.mockReset().mockResolvedValue(saved);
  onOpenChange.mockReset();
});
afterEach(cleanup);

it("connects a service with the entered settings, on by default, and stays open on it", async () => {
  renderDialog(props(null));

  fillNew();
  fireEvent.click(button("Anslut"));

  await waitFor(() => expect(create).toHaveBeenCalledOnce());
  expect(create).toHaveBeenCalledWith({
    name: "Vemsa Sundsvall",
    endpoint_url: "https://vemsa.sundsvall.se",
    api_key: "secret-key",
    is_enabled: true,
    security_classification: null
  });
  expect(await screen.findByRole("heading", { name: "Vemsa Sundsvall är ansluten" })).toBeTruthy();
  // The key is saved and never shown again; the field now offers to replace it.
  expect(field(KEY).value).toBe("");
  expect(field(KEY).type).toBe("password");
  // Everything is saved, so the only way out is "Klar", and it has the focus.
  await waitFor(() => expect(document.activeElement).toBe(button("Klar")));
  expect(screen.queryByRole("button", { name: "Spara" })).toBeNull();
  expect(onOpenChange).not.toHaveBeenCalled();
  await act(async () => {
    await expectNoAxeViolations(document.body);
  });
});

it("shows the new service's test and lets a refused key be fixed in place", async () => {
  const { rerender } = renderDialog(props(null));
  fillNew("wrong-key");
  fireEvent.click(button("Anslut"));
  await waitFor(() => expect(create).toHaveBeenCalledOnce());

  rerender(props(null, { checking: true }));
  expect(await screen.findByText("Testar anslutningen…")).toBeTruthy();
  rerender(
    props(null, {
      check: {
        outcome: "credentials_rejected",
        identifies_speakers: null,
        times_words: null,
        reason: "credentials",
        status_code: null,
        service_version: null,
        checked_at: "2026-10-09T07:00:00Z"
      }
    })
  );
  expect(await screen.findByText("Nyckeln godtogs inte")).toBeTruthy();

  type(KEY, "right-key");
  fireEvent.click(button("Spara"));

  await waitFor(() => expect(update).toHaveBeenCalledOnce());
  expect(update).toHaveBeenCalledWith("s1", { api_key: "right-key" });
  expect(screen.getByRole("dialog")).toBeTruthy();
  expect(onOpenChange).not.toHaveBeenCalled();
});

it("asks for a new key before saving a moved address", async () => {
  renderDialog(props(saved));

  type(ADDRESS, "https://vemsa2.sundsvall.se");
  expect(screen.getByText("Ange en ny nyckel när du byter adress.")).toBeTruthy();

  fireEvent.click(button("Spara"));
  expect(update).not.toHaveBeenCalled();
  expect(field(KEY).getAttribute("aria-invalid")).toBe("true");
  // Focus goes to the field that needs it (WCAG 3.3.1).
  expect(document.activeElement).toBe(field(KEY));
});

it("keeps the entered values and points at the name when it is taken", async () => {
  create.mockRejectedValue(new EneoApiError("Name taken", { status: 409, code: 9017 }));
  renderDialog(props(null));

  fillNew();
  fireEvent.click(button("Anslut"));

  expect(await screen.findByText("Det finns redan en tjänst med det namnet.")).toBeTruthy();
  expect(field(NAME).value).toBe("Vemsa Sundsvall");
  expect(field(ADDRESS).value).toBe("https://vemsa.sundsvall.se");
  expect(field(KEY).value).toBe("secret-key");
  await waitFor(() => expect(document.activeElement).toBe(field(NAME)));
  expect(onOpenChange).not.toHaveBeenCalled();
});

it("explains a refused address in the user's language", async () => {
  create.mockRejectedValue(
    new EneoApiError("Invalid", {
      status: 422,
      code: 9000,
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
  renderDialog(props(null));

  type(NAME, "Vemsa Sundsvall");
  type(ADDRESS, "https://user:pw@vemsa.sundsvall.se");
  type(KEY, "secret-key");
  fireEvent.click(button("Anslut"));

  expect(
    await screen.findByText(
      "Adressen får inte innehålla användarnamn eller lösenord. Ange API-nyckeln i sitt eget fält."
    )
  ).toBeTruthy();
  expect(field(ADDRESS).getAttribute("aria-invalid")).toBe("true");
});

it("sends only what the administrator changed", async () => {
  // With enforcement off the API reads a stored classification as null; a
  // rename that echoed it back would clear it.
  renderDialog(props(saved));

  type(NAME, "Vemsa Sundsvall Nord");
  fireEvent.click(button("Spara"));

  await waitFor(() => expect(update).toHaveBeenCalledOnce());
  expect(update).toHaveBeenCalledWith("s1", { name: "Vemsa Sundsvall Nord" });
  await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
});

it("treats a trailing slash or /v1 as the saved address", () => {
  renderDialog(props(saved));

  for (const same of ["https://vemsa.sundsvall.se/", "https://vemsa.sundsvall.se/v1/"]) {
    type(ADDRESS, same);
    expect(screen.queryByText("Ange en ny nyckel när du byter adress.")).toBeNull();
  }

  // Nothing changed, so there is nothing to save.
  expect(screen.queryByRole("button", { name: "Spara" })).toBeNull();
  fireEvent.click(button("Klar"));
  expect(onOpenChange).toHaveBeenCalledWith(false);
  expect(update).not.toHaveBeenCalled();
});

it("locks the fields while a save is answering, so nothing typed meanwhile is lost", async () => {
  let answer: (service: TranscriptionService) => void = () => {};
  create.mockReturnValueOnce(new Promise((resolve) => (answer = resolve)));
  renderDialog(props(null));

  fillNew();
  fireEvent.click(button("Anslut"));

  await waitFor(() => expect(field(KEY).disabled).toBe(true));
  expect(field(NAME).disabled).toBe(true);
  expect((button("Avbryt") as HTMLButtonElement).disabled).toBe(true);
  await act(async () => answer(saved));
  await waitFor(() => expect(field(KEY).disabled).toBe(false));
});

it("counts a saved classification as saved even when the service reads it back as none", async () => {
  // With classification enforcement off the API reads every classification as none.
  const onTest = vi.fn();
  const { dialog } = renderDialog(props(null, { onTest }));

  fillNew();
  fireEvent.click(within(dialog).getByRole("combobox", { name: /Säkerhetsklass/ }));
  fireEvent.click(await screen.findByRole("option", { name: "Intern" }));
  fireEvent.click(button("Anslut"));
  await waitFor(() => expect(create).toHaveBeenCalledOnce());
  expect(create.mock.calls[0]![0]).toMatchObject({ security_classification: { id: "c1" } });

  expect(await screen.findByRole("button", { name: "Klar" })).toBeTruthy();
  fireEvent.click(button("Testa anslutningen"));
  expect(onTest).toHaveBeenCalledOnce();
  expect(screen.queryByText("Spara först för att testa de nya inställningarna.")).toBeNull();
});

it("asks to save first before testing settings that are not saved", () => {
  const onTest = vi.fn();
  renderDialog(props(saved, { onTest }));

  type(NAME, "Vemsa Nord");
  fireEvent.click(button("Testa anslutningen"));

  expect(onTest).not.toHaveBeenCalled();
  expect(screen.getByText("Spara först för att testa de nya inställningarna.")).toBeTruthy();
});
