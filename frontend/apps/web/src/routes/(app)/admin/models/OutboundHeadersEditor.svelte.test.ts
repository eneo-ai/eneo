import type { OutboundHeaderOptions, OutboundHeaderPublic } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import OutboundHeadersEditorFixture from "./OutboundHeadersEditorFixture.svelte";
import "../../../../app.css";

const options: OutboundHeaderOptions = {
  dynamic_values: [
    {
      token: "user.employeeNumber",
      source: "scim_enterprise",
      attribute: "employeeNumber",
      classification: "identifying"
    },
    {
      token: "user.department",
      source: "scim_enterprise",
      attribute: "department",
      classification: "organisational"
    }
  ],
  supported_provider_types: ["hosted_vllm", "vllm"],
  max_headers: 10
};

const secretHeader: OutboundHeaderPublic = {
  id: "h1",
  name: "X-Credential",
  value: "********",
  encoding: "none",
  secret: true,
  on_missing: "omit",
  fallback: null,
  classification: null
};

const plainHeader: OutboundHeaderPublic = {
  id: "h2",
  name: "X-Org-Unit",
  value: "{{user.department}}",
  encoding: "percent",
  secret: false,
  on_missing: "omit",
  fallback: null,
  classification: "organisational"
};

function renderEditor(
  props: Partial<Parameters<typeof render<typeof OutboundHeadersEditorFixture>>[1]> = {}
) {
  const onPayload = vi.fn();
  render(OutboundHeadersEditorFixture, { options, onPayload, ...props });
  const lastPayload = () => onPayload.mock.lastCall?.[0];
  return { lastPayload };
}

const changeValue = (name: string) =>
  page.getByRole("button", { name: m.outbound_headers_change_value({ name }) });
const valueInput = () => page.getByLabelText(m.outbound_headers_value(), { exact: true });

describe("stored secret values", () => {
  it("can go back to the stored value after Change", async () => {
    const { lastPayload } = renderEditor({ headers: [secretHeader] });

    await changeValue("X-Credential").click();
    await expect.element(valueInput()).toHaveFocus();
    await valueInput().fill("new-credential");
    expect(lastPayload()[0].value).toBe("new-credential");

    await page.getByRole("button", { name: m.outbound_headers_keep_value() }).click();

    await expect.element(changeValue("X-Credential")).toHaveFocus();
    expect(lastPayload()[0]).not.toHaveProperty("value");
  });

  it("returns to the stored value when Secret is unticked and ticked again", async () => {
    const { lastPayload } = renderEditor({ headers: [secretHeader] });
    const secret = page.getByRole("checkbox", { name: m.outbound_headers_secret() });

    await secret.click();
    await expect.element(valueInput()).toBeVisible();
    await expect.element(page.getByText(m.outbound_headers_secret_reenter())).toBeVisible();

    await secret.click();

    await expect.element(changeValue("X-Credential")).toBeVisible();
    expect(lastPayload()[0]).not.toHaveProperty("value");
  });
});

describe("states", () => {
  it("shows only the unsupported note for other provider types", async () => {
    renderEditor({ providerType: "openai", headers: [plainHeader] });

    await expect.element(page.getByText(m.outbound_headers_unsupported())).toBeVisible();
    await expect.element(page.getByText(m.outbound_headers_description())).not.toBeInTheDocument();
    await expect
      .element(page.getByRole("button", { name: m.outbound_headers_add() }))
      .not.toBeInTheDocument();
  });

  it("offers a retry when the options request failed", async () => {
    const onRetry = vi.fn();
    renderEditor({ options: null, optionsError: true, onRetry, editing: true });

    await expect.element(page.getByText(m.outbound_headers_options_failed())).toBeVisible();
    await expect.element(page.getByText(m.outbound_headers_options_failed_kept())).toBeVisible();
    await page.getByRole("button", { name: m.retry() }).click();

    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("warns what blocking the request means", async () => {
    renderEditor({ headers: [{ ...plainHeader, on_missing: "fail" }] });

    await expect.element(page.getByText(m.outbound_headers_fail_warning())).toBeVisible();
  });

  it("shows the notice for a saved secret from its stored classification", async () => {
    renderEditor({ headers: [{ ...secretHeader, classification: "identifying" }] });

    await expect.element(page.getByText(m.outbound_headers_notice_identifying())).toBeVisible();
  });

  it("warns about secret values over plain http, but not on loopback", async () => {
    renderEditor({ headers: [secretHeader], endpoint: "http://vllm.internal:8000/v1" });
    await expect.element(page.getByText(m.outbound_headers_plain_http_warning())).toBeVisible();
  });

  it("warns about non-secret user attributes over plain http", async () => {
    renderEditor({
      headers: [{ ...plainHeader, value: "{{user.employeeNumber}}" }],
      endpoint: "http://vllm.internal:8000/v1"
    });
    await expect.element(page.getByText(m.outbound_headers_plain_http_warning())).toBeVisible();
  });

  it("does not warn about fixed text over plain http", async () => {
    renderEditor({
      headers: [{ ...plainHeader, value: "eu-north", classification: null }],
      endpoint: "http://vllm.internal:8000/v1"
    });
    await expect
      .element(page.getByText(m.outbound_headers_plain_http_warning()))
      .not.toBeInTheDocument();
  });

  it("does not warn on loopback", async () => {
    renderEditor({ headers: [secretHeader], endpoint: "http://127.0.0.1:8000/v1" });
    await expect
      .element(page.getByText(m.outbound_headers_plain_http_warning()))
      .not.toBeInTheDocument();
  });

  it("flags an unknown dynamic value before save", async () => {
    renderEditor({ headers: [{ ...plainHeader, value: "{{user.departmnet}}" }] });

    await expect
      .element(page.getByText(m.outbound_headers_unknown_token({ tokens: "{{user.departmnet}}" })))
      .toBeVisible();
    await expect.element(valueInput()).toHaveAttribute("aria-invalid", "true");
    await expect.element(page.getByText(m.outbound_headers_incomplete_hint())).toBeVisible();
  });
});

describe("focus", () => {
  it("moves to the new name field on add, and back to Add on remove", async () => {
    renderEditor();
    const add = page.getByRole("button", { name: m.outbound_headers_add() });

    await add.click();
    await expect
      .element(page.getByLabelText(m.outbound_headers_name(), { exact: true }))
      .toHaveFocus();

    await page
      .getByRole("button", {
        name: m.outbound_headers_remove_named({ name: m.outbound_headers_unnamed({ position: 1 }) })
      })
      .click();
    await expect.element(add).toHaveFocus();
  });
});
