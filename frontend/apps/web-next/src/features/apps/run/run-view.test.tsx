// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import type { App } from "../apps";
import { RunView } from "./run-view";

const api = vi.hoisted(() => ({ POST: vi.fn(), DELETE: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("@/features/jobs/use-jobs", () => ({ useJobs: () => ({ trackJob: vi.fn() }) }));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const limit = { max_files: 2, max_size: 10_000_000 };
const pdf = { mimetype: "application/pdf", size_limit: 10_000_000, extensions: ["pdf"] };

function app(fields: Pick<App["input_fields"][number], "type">[]): App {
  return {
    id: "app-1",
    name: "Sammanfattaren",
    description: null,
    input_fields: fields.map(({ type }) => ({ type, limit, accepted_file_types: [pdf] })),
    completion_model: { id: "model-1", name: "gpt-5" }
  } as unknown as App;
}

it("shows missing input at the inputs on submit, and moves focus to the first", async () => {
  api.POST.mockResolvedValue({ data: { id: "run-1" }, response: new Response("{}") });
  renderInApp(<RunView app={app([{ type: "text-field" }])} resultHref={(id) => `/runs/${id}`} />);

  const submit = screen.getByRole("button", { name: "Skicka" });
  expect(submit.hasAttribute("disabled")).toBe(false);
  fireEvent.click(submit);

  const question = screen.getByRole("textbox", { name: "Skriv din fråga här" });
  expect(document.activeElement).toBe(question);
  const inputs = screen.getByRole("group", { name: "Indata" });
  expect(inputs.getAttribute("aria-invalid")).toBe("true");
  expect(document.getElementById(inputs.getAttribute("aria-describedby") ?? "")?.textContent).toBe(
    "Indata krävs för att köra denna app"
  );
  expect(api.POST).not.toHaveBeenCalled();

  fireEvent.change(question, { target: { value: "Sammanfatta protokollet" } });
  expect(inputs.getAttribute("aria-invalid")).toBeNull();
  fireEvent.click(submit);
  await waitFor(() =>
    expect(api.POST).toHaveBeenCalledWith("/api/v1/apps/{id}/runs/", {
      params: { path: { id: "app-1" } },
      body: { files: [], text: "Sammanfatta protokollet" }
    })
  );
});

it("moves focus to an upload input's file picker when it is the first input", () => {
  renderInApp(<RunView app={app([{ type: "text-upload" }])} resultHref={(id) => `/runs/${id}`} />);

  fireEvent.click(screen.getByRole("button", { name: "Skicka" }));

  const group = screen.getByRole("group", { name: "Indata" });
  expect(document.activeElement?.tagName).toBe("BUTTON");
  expect(group.contains(document.activeElement)).toBe(true);
  expect(api.POST).not.toHaveBeenCalled();
});

it("asks to wait while a file uploads, and keeps focus on a busy submit", async () => {
  let uploaded: (value: unknown) => void = () => {};
  let created: (value: unknown) => void = () => {};
  api.POST.mockImplementation((path: string) =>
    path === "/api/v1/files/"
      ? new Promise((resolve) => {
          uploaded = resolve;
        })
      : new Promise((resolve) => {
          created = resolve;
        })
  );
  const { container } = renderInApp(
    <RunView app={app([{ type: "text-upload" }])} resultHref={(id) => `/runs/${id}`} />
  );
  const picker = container.querySelector<HTMLInputElement>('input[type="file"]')!;
  fireEvent.change(picker, {
    target: { files: [new File(["%PDF"], "protokoll.pdf", { type: "application/pdf" })] }
  });
  await screen.findByText("protokoll.pdf");

  const submit = screen.getByRole("button", { name: "Skicka" });
  submit.focus();
  fireEvent.click(submit);
  const notice = await screen.findByText("Vänta tills filerna har laddats upp.");
  expect(notice.getAttribute("role")).toBe("status");
  expect(document.activeElement).toBe(submit);
  expect(api.POST).toHaveBeenCalledTimes(1);

  uploaded({ data: { id: "file-1" }, response: new Response("{}") });
  await waitFor(() => expect(notice.textContent).toBe(""));
  fireEvent.click(submit);
  const busy = await screen.findByRole("button", { name: "Skickar..." });
  expect(busy).toBe(submit);
  expect(busy.getAttribute("aria-busy")).toBe("true");
  expect(document.activeElement).toBe(busy);
  fireEvent.click(busy);
  expect(api.POST).toHaveBeenCalledTimes(2);
  created({ data: { id: "run-1" }, response: new Response("{}") });
});
