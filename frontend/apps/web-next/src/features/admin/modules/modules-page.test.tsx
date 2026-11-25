// @vitest-environment jsdom
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import messages from "@/lib/i18n/messages/sv.json";

const api = vi.hoisted(() => ({
  installations: [] as object[],
  GET: vi.fn((path: string) =>
    Promise.resolve({
      data:
        path === "/api/v1/admin/modules/service-keys/"
          ? { items: [], next_cursor: null }
          : { items: path === "/api/v1/admin/modules/" ? api.installations : [] },
      response: new Response("{}")
    })
  ),
  PUT: vi.fn()
}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
const toastApiError = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/toast", () => ({ toastApiError }));

import { ModulesPage } from "./modules-page";

beforeEach(() => {
  vi.resetAllMocks();
});
afterEach(() => {
  vi.restoreAllMocks();
  api.installations = [];
});

it("introduces the page under its title, not under the installed modules", () => {
  renderInApp(<ModulesPage title="Moduler" />);
  const intro = screen.getByText(
    "Installera och konfigurera moduler för den här Eneo-installationen. Organisationsisoleringen hanteras automatiskt."
  );
  expect(intro.closest("section")).toBeNull();
  expect(
    screen.getByRole("heading", { level: 1, name: "Moduler" }).parentElement?.contains(intro)
  ).toBe(true);
});

const serviceKey = (id: string, name: string, suffix: string) => ({
  id,
  name,
  key_prefix: "sk_",
  key_suffix: suffix
});

it("offers only the service keys the backend lets a module bind, from every page", async () => {
  api.GET.mockImplementation(((
    path: string,
    init?: { params?: { query?: { cursor?: string } } }
  ) => {
    const cursor = init?.params?.query?.cursor;
    const data =
      path === "/api/v1/admin/modules/service-keys/"
        ? cursor === "page-2"
          ? { items: [serviceKey("k2", "Ärendetjänst", "b2b2")], next_cursor: null }
          : { items: [serviceKey("k1", "Diarietjänst", "a1a1")], next_cursor: "page-2" }
        : path === "/api/v1/admin/api-keys"
          ? // Every key of the organization, a person's own key among them.
            {
              items: [
                serviceKey("k1", "Diarietjänst", "a1a1"),
                serviceKey("k3", "Annas nyckel", "c3c3")
              ],
              next_cursor: null
            }
          : { items: [] };
    return Promise.resolve({ data, response: new Response("{}") });
  }) as never);
  renderInApp(<ModulesPage title="Moduler" />);

  const select = screen.getByLabelText("Tjänstenyckel") as HTMLSelectElement;
  await waitFor(() => expect(select.disabled).toBe(false));
  const options = [...select.options].map((option) => option.textContent);
  expect(options).toContain("Diarietjänst · sk_••••a1a1");
  expect(options).toContain("Ärendetjänst · sk_••••b2b2");
  expect(options.some((option) => option?.includes("Annas nyckel"))).toBe(false);
  // At most the backend's page size, and the next page by its cursor.
  expect(api.GET).toHaveBeenCalledWith("/api/v1/admin/modules/service-keys/", {
    params: { query: { limit: 100 } }
  });
  expect(api.GET).toHaveBeenCalledWith("/api/v1/admin/modules/service-keys/", {
    params: { query: { limit: 100, cursor: "page-2" } }
  });
});

const problemOf = (control: HTMLElement) =>
  document.getElementById(control.getAttribute("aria-describedby")!.split(" ")[0]!)?.textContent;

it("shows each problem at its field on install, and moves focus to the first", async () => {
  const { container } = renderInApp(<ModulesPage title="Moduler" />);
  const install = screen.getByRole("button", { name: "Installera modul" });
  // Never disabled: a disabled button says nothing about what is missing.
  expect((install as HTMLButtonElement).disabled).toBe(false);
  // Loaded: the service keys to pick from.
  await waitFor(() =>
    expect((screen.getByLabelText("Tjänstenyckel") as HTMLSelectElement).disabled).toBe(false)
  );

  fireEvent.click(install);
  const key = screen.getByLabelText("Modulnyckel");
  const urls = screen.getByLabelText("Callback-URL:er");
  const serviceKey = screen.getByLabelText("Tjänstenyckel");
  expect(problemOf(key)).toBe("Detta fält är obligatoriskt");
  expect(problemOf(urls)).toBe("Detta fält är obligatoriskt");
  expect(problemOf(serviceKey)).toBe("Detta fält är obligatoriskt");
  expect(document.activeElement).toBe(key);
  await expectNoAxeViolations(container);

  // The key's format is checked too.
  fireEvent.change(key, { target: { value: "-diariet" } });
  fireEvent.click(install);
  expect(problemOf(key)).toBe(
    "Börja med en bokstav eller siffra och använd bara bokstäver, siffror, punkt, bindestreck och understreck."
  );

  fireEvent.change(key, { target: { value: "diariet" } });
  fireEvent.click(install);
  expect(key.getAttribute("aria-invalid")).toBeNull();
  expect(document.activeElement).toBe(urls);
  expect(api.PUT).not.toHaveBeenCalled();
});

it("shows the speech-to-text module's own values as examples, and where the key comes from", () => {
  renderInApp(<ModulesPage title="Moduler" />);

  const key = screen.getByLabelText("Modulnyckel") as HTMLInputElement;
  expect(key.placeholder).toBe("speech-to-text");
  expect(key.getAttribute("aria-describedby")).toContain("module-key-help");
  expect(document.getElementById("module-key-help")?.textContent).toBe(
    "Samma värde som MODULE_KEY i modulens inställningar, till exempel speech-to-text. Använd gemener, siffror och bindestreck. Nyckeln kan inte ändras efter installationen."
  );
  expect((screen.getByLabelText("Callback-URL:er") as HTMLTextAreaElement).placeholder).toBe(
    "https://tal.example.se/api/auth/callback"
  );
  expect(document.getElementById("redirect-uris-help")?.textContent).toBe(
    "Ange en exakt callback-URL per rad, oftast modulens adress följd av /api/auth/callback. Eneo skickar inloggningsbiljetter bara till dessa URL:er."
  );
});

it("says why an installed module is incomplete, and nothing under a configured one", async () => {
  const callback = ["https://tal.example.se/api/auth/callback"];
  api.installations = [
    { module_id: "m1", module_key: "utan-nyckel", configured: false, redirect_uris: callback },
    {
      module_id: "m2",
      module_key: "utan-callback",
      configured: false,
      redirect_uris: [],
      service_key_id: "k9"
    },
    { module_id: "m3", module_key: "utan-bada", configured: false, redirect_uris: [] },
    // As the backend says: configured decides, not the fields read here.
    { module_id: "m4", module_key: "klar", configured: true, redirect_uris: [] }
  ];
  const { container } = renderInApp(<ModulesPage title="Moduler" />);

  const card = async (moduleKey: string) =>
    (await screen.findByRole("heading", { name: moduleKey })).closest("li")!.textContent;
  const noKey = "Ingen tjänstenyckel är vald.";
  const noCallback = "Ingen callback-URL är angiven.";
  const effect = "Användare kan inte logga in i modulen.";

  expect(await card("utan-nyckel")).toContain(`Ofullständig${noKey} ${effect}`);
  expect(await card("utan-callback")).toContain(`Ofullständig${noCallback} ${effect}`);
  expect(await card("utan-bada")).toContain(`Ofullständig${noKey} ${noCallback} ${effect}`);
  const done = await card("klar");
  expect(done).toContain("Konfigurerad");
  expect(done).not.toContain(effect);
  await expectNoAxeViolations(container);
});

it("reports a failed read once, in the user's language, with a retry", async () => {
  api.GET.mockImplementationOnce(() =>
    Promise.resolve({
      error: { message: "Internal server error", eneo_error_code: 9024 },
      response: new Response(null, { status: 500 })
    } as never)
  );
  renderInApp(<ModulesPage title="Moduler" />);

  await screen.findByRole("button", { name: "Försök igen" });
  const alert = screen.getByText("Innehållet kunde inte hämtas").closest('[role="alert"]')!;
  expect(alert.textContent).not.toContain("Internal server error");
  expect(alert.textContent).toContain("Innehållet kunde inte hämtas");
  expect(screen.getAllByText("Innehållet kunde inte hämtas")).toHaveLength(1);
  // The read failure is reported inline only; the toast is for failed changes.
  expect(toastApiError).not.toHaveBeenCalled();
});

it("tells screen readers the installed modules are loading", () => {
  api.GET.mockImplementationOnce(() => new Promise(() => {}));
  renderInApp(<ModulesPage title="Moduler" />);

  const label = screen.getByText(messages.loading);
  const region = label.closest<HTMLElement>('[role="status"]');
  expect(region).not.toBeNull();
  expect(region!.getAttribute("aria-busy")).toBe("true");
});

it("shows a failed read as an error only, and keeps its focused retry busy while it retries", async () => {
  let reads = 0;
  api.GET.mockImplementation((path: string) => {
    if (path !== "/api/v1/admin/modules/")
      return Promise.resolve({
        data: { items: [], next_cursor: null },
        response: new Response("{}")
      });
    reads += 1;
    return reads === 1
      ? (Promise.resolve({
          error: { message: "Internal server error", eneo_error_code: 9024 },
          response: new Response(null, { status: 500 })
        }) as never)
      : new Promise(() => {});
  });
  renderInApp(<ModulesPage title="Moduler" />);

  const retry = await screen.findByRole("button", { name: "Försök igen" });
  // A failed read is not an empty list.
  expect(screen.queryByText("Inga moduler är installerade")).toBeNull();

  retry.focus();
  fireEvent.click(retry);
  await waitFor(() => expect(retry.getAttribute("aria-busy")).toBe("true"));
  expect(retry.isConnected).toBe(true);
  expect(document.activeElement).toBe(retry);
  expect(screen.queryByText(messages.loading)).toBeNull();
});

it.each([
  [false, "smooth"],
  [true, "auto"]
])(
  "brings the form into view on edit, smoothly unless motion is reduced (reduce: %s)",
  async (reduce, behavior) => {
    api.installations = [
      { module_id: "m1", module_key: "registrator", configured: true, redirect_uris: [] }
    ];
    const media = window.matchMedia;
    vi.spyOn(window, "matchMedia").mockImplementation((query: string) =>
      query === "(prefers-reduced-motion: reduce)"
        ? ({ ...media(query), matches: reduce } as MediaQueryList)
        : media(query)
    );
    const scroll = vi.fn();
    HTMLElement.prototype.scrollIntoView = scroll;
    renderInApp(<ModulesPage title="Moduler" />);

    fireEvent.click(await screen.findByRole("button", { name: "Redigera" }));

    expect(scroll).toHaveBeenCalledWith({ behavior, block: "start" });
  }
);
