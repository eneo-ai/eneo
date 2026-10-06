// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { ServicePlayground } from "./playground";

const api = vi.hoisted(() => ({ POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("shows an empty input at its field on run, and keeps focus on a busy Run", async () => {
  let resolve: (value: unknown) => void = () => {};
  api.POST.mockImplementation(
    () =>
      new Promise((done) => {
        resolve = done;
      })
  );
  renderInApp(<ServicePlayground serviceId="service-1" />);
  const run = screen.getByRole("button", { name: "Kör denna tjänst" });
  expect(run.hasAttribute("disabled")).toBe(false);

  fireEvent.click(run);

  const input = screen.getByRole("textbox", { name: "Indata" });
  expect(document.activeElement).toBe(input);
  expect(input.getAttribute("aria-invalid")).toBe("true");
  expect(document.getElementById(input.getAttribute("aria-describedby") ?? "")?.textContent).toBe(
    "Detta fält är obligatoriskt"
  );
  expect(api.POST).not.toHaveBeenCalled();

  fireEvent.change(input, { target: { value: "Diarienummer 2024-123" } });
  run.focus();
  fireEvent.click(run);
  const busy = await screen.findByRole("button", { name: "Kör..." });
  expect(busy).toBe(run);
  expect(busy.getAttribute("aria-busy")).toBe("true");
  expect(document.activeElement).toBe(busy);
  fireEvent.click(busy);
  expect(api.POST).toHaveBeenCalledTimes(1);
  expect(api.POST).toHaveBeenCalledWith("/api/v1/services/{id}/run/", {
    params: { path: { id: "service-1" } },
    body: { input: "Diarienummer 2024-123" }
  });

  resolve({ data: { output: "Klart" }, response: new Response("{}") });
  await waitFor(() => expect(screen.getByText("Klart")).toBeTruthy());
});
