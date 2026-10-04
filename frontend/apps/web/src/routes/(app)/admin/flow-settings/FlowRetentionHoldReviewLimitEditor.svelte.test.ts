import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { beforeEach, describe, expect, test, vi } from "vitest";

const getFlowRetentionHoldReviewLimit = vi.hoisted(() => vi.fn());
const replaceFlowRetentionHoldReviewLimit = vi.hoisted(() => vi.fn());
const toastSuccess = vi.hoisted(() => vi.fn());
const toastErrorMock = vi.hoisted(() => vi.fn());

vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    settings: { getFlowRetentionHoldReviewLimit, replaceFlowRetentionHoldReviewLimit }
  })
}));

vi.mock("$lib/components/toast", () => ({
  toast: { success: toastSuccess, error: vi.fn() }
}));

vi.mock("$lib/core/errors", () => ({
  toastError: toastErrorMock
}));

vi.mock("$lib/paraglide/messages", async () => {
  const { default: swedishMessages } = await import("../../../../../messages/sv.json");

  return {
    m: new Proxy<Record<string, unknown>>(
      {},
      {
        get: (_target, key) => {
          const label = String(key);
          return (params?: Record<string, unknown>) => {
            const template = (swedishMessages as Record<string, string>)[label];
            if (typeof template !== "string") {
              return params ? `${label} ${JSON.stringify(params)}` : label;
            }
            return template.replace(/\{(\w+)\}/g, (_match, name: string) =>
              String(params?.[name] ?? `{${name}}`)
            );
          };
        }
      }
    )
  };
});

vi.mock("$lib/paraglide/runtime", () => ({
  getLocale: () => "sv"
}));

import FlowRetentionHoldReviewLimitEditor from "./FlowRetentionHoldReviewLimitEditor.svelte";

const LABEL = "Längsta tid till omprövning (dagar)";

function renderEditor(limit: { days: number; is_default: boolean | null } | null) {
  const onChange = vi.fn();
  render(FlowRetentionHoldReviewLimitEditor, { limit, onChange } as never);
  return onChange;
}

describe("review limit editor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test("an unreadable limit is said, not shown as a default, and can be read again", async () => {
    getFlowRetentionHoldReviewLimit.mockResolvedValue({ days: 90, is_default: false });
    const onChange = renderEditor(null);

    await expect
      .element(page.getByText("Den längsta tiden till omprövning kunde inte hämtas."))
      .toBeVisible();
    await expect.element(page.getByLabelText(LABEL)).not.toBeInTheDocument();
    await page.getByRole("button", { name: "Uppdatera" }).click();
    await vi.waitFor(() =>
      expect(onChange).toHaveBeenCalledExactlyOnceWith({ days: 90, is_default: false })
    );
  });

  test("a changed limit can return to the default", async () => {
    replaceFlowRetentionHoldReviewLimit.mockResolvedValue({ days: 365, is_default: true });
    const onChange = renderEditor({ days: 90, is_default: false });

    await expect.element(page.getByLabelText(LABEL)).toHaveValue(90);
    await page.getByRole("button", { name: "Använd standard (365 dagar)" }).click();
    await vi.waitFor(() =>
      expect(replaceFlowRetentionHoldReviewLimit).toHaveBeenCalledExactlyOnceWith({ days: null })
    );
    expect(onChange).toHaveBeenCalledWith({ days: 365, is_default: true });
  });

  test("the default is named and offers no reset", async () => {
    renderEditor({ days: 365, is_default: true });

    await expect.element(page.getByText(/Standardvärdet 365 dagar gäller/)).toBeVisible();
    await expect
      .element(page.getByRole("button", { name: /Använd standard/ }))
      .not.toBeInTheDocument();
  });

  test("an invalid value says why Save is off", async () => {
    renderEditor({ days: 365, is_default: true });

    await page.getByLabelText(LABEL).fill("3000");
    await expect.element(page.getByText("Ange ett heltal från 1 till 2555 dagar.")).toBeVisible();
    await expect.element(page.getByRole("button", { name: "Spara" })).toBeDisabled();
  });

  test.each([
    ["retention_permission_required", "Du saknar behörigheten Gallring – hantera regler"],
    ["flow_retention_lock_busy", "En annan gallring eller ändring pågår"]
  ])("a %s refusal is shown in the page language", async (code, text) => {
    replaceFlowRetentionHoldReviewLimit.mockRejectedValue({
      status: code === "flow_retention_lock_busy" ? 409 : 403,
      code: 9000,
      message: "raw backend text",
      response: { code }
    });
    renderEditor({ days: 365, is_default: true });

    await page.getByLabelText(LABEL).fill("180");
    await page.getByRole("button", { name: "Spara" }).click();
    await expect.element(page.getByText(new RegExp(text))).toBeVisible();
    await expect.element(page.getByText("raw backend text")).not.toBeInTheDocument();
    expect(toastErrorMock).not.toHaveBeenCalled();
  });

  test("a refreshed limit replaces an untouched draft and keeps a deliberate edit", async () => {
    const onChange = vi.fn();
    const { rerender } = render(FlowRetentionHoldReviewLimitEditor, {
      limit: { days: 365, is_default: true },
      onChange
    } as never);
    const field = page.getByLabelText(LABEL);
    await expect.element(field).toHaveValue(365);

    await rerender({ limit: { days: 90, is_default: false } });
    await expect.element(field).toHaveValue(90);
    await expect.element(page.getByRole("button", { name: "Spara" })).toBeDisabled();

    await field.fill("120");
    await rerender({ limit: { days: 60, is_default: false } });
    await expect.element(field).toHaveValue(120);
    await expect.element(page.getByRole("button", { name: "Spara" })).toBeEnabled();
  });

  test("a refused reload is shown while the limit is still unknown", async () => {
    getFlowRetentionHoldReviewLimit.mockRejectedValue({
      status: 403,
      code: 9000,
      response: { code: "retention_person_required" }
    });
    renderEditor(null);

    await page.getByRole("button", { name: "Uppdatera" }).click();
    await expect
      .element(page.getByText(/Du saknar behörigheten Gallring – hantera regler/))
      .toBeVisible();
    await expect
      .element(page.getByText("Den längsta tiden till omprövning kunde inte hämtas."))
      .toBeVisible();
    expect(toastErrorMock).not.toHaveBeenCalled();
  });
});
