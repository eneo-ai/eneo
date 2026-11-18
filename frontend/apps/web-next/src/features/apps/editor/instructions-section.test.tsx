// @vitest-environment jsdom
import { useMutation } from "@tanstack/react-query";
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, assert, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import type { App } from "../apps";
import type { AppUpdate } from "./use-app";
import { InstructionsSection } from "./instructions-section";
const api = vi.hoisted(() => ({ GET: vi.fn() }));
const update = vi.hoisted(() => vi.fn<(body: unknown) => Promise<unknown>>().mockResolvedValue({}));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("./use-app", () => ({
  useUpdateApp: () =>
    useMutation({ scope: { id: "app:app" }, mutationFn: (body: unknown) => update(body) })
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  update.mockReset().mockResolvedValue({});
});
it.each([false, true])(
  "restores provenance through app autosave even for identical text: %s",
  async (identical) => {
    const old = {
      id: "old",
      text: "App restored body",
      description: "Historical app marker",
      created_at: "2026-10-01T12:00:00Z",
      is_selected: false,
      user: { id: "user-1", email: "owner@example.se" }
    };
    api.GET.mockImplementation(async (path) => ({
      data: path.includes("/prompts/{id}") ? old : { items: [old] },
      response: new Response("{}")
    }));
    renderInApp(
      <InstructionsSection
        app={
          {
            id: "app",
            prompt: { text: identical ? "App restored body" : "Current app body" }
          } as unknown as App
        }
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Visa prompthistorik" }));
    fireEvent.click(await screen.findByRole("button", { name: /Historical app marker/ }));
    await screen.findByRole("button", { name: "Återställ denna version" });
    fireEvent.click(
      screen.getByRole("button", { name: /Återställ denna version|Använd denna version/ })
    );
    await waitFor(() =>
      expect(update).toHaveBeenCalledWith({
        prompt: {
          text: "App restored body",
          description: expect.stringMatching(/^Återställd prompt från /)
        }
      })
    );
  }
);

it("deduplicates untouched text and omits description from ordinary app edits", async () => {
  renderInApp(
    <InstructionsSection
      app={
        {
          id: "app",
          prompt: { text: "Current app body", description: "Saved marker" }
        } as unknown as App
      }
    />
  );
  const field = screen.getByRole("textbox", { name: "Prompt" });
  await act(async () => {
    fireEvent.blur(field);
  });
  expect(update).not.toHaveBeenCalled();
  fireEvent.change(field, { target: { value: "Uncommitted edit" } });
  fireEvent.change(field, { target: { value: "Current app body" } });
  await act(async () => {
    fireEvent.blur(field);
  });
  expect(update).not.toHaveBeenCalled();
  fireEvent.change(field, { target: { value: "Manual app body" } });
  fireEvent.blur(field);
  await waitFor(() => expect(update).toHaveBeenCalledWith({ prompt: { text: "Manual app body" } }));
});

it("does not restore old provenance when manual A returns while save B is held", async () => {
  let release!: () => void;
  const held = new Promise<unknown>((resolve) => {
    release = () => resolve({});
  });
  update.mockImplementationOnce(() => held).mockResolvedValue({});
  renderInApp(
    <InstructionsSection
      app={
        {
          id: "app",
          prompt: { text: "Original A", description: "Restored original marker" }
        } as unknown as App
      }
    />
  );
  const field = screen.getByRole("textbox", { name: "Prompt" });
  fireEvent.change(field, { target: { value: "Manual B" } });
  fireEvent.blur(field);
  await waitFor(() => expect(update).toHaveBeenCalledWith({ prompt: { text: "Manual B" } }));
  try {
    fireEvent.change(field, { target: { value: "Original A" } });
    fireEvent.blur(field);
    release();
    await waitFor(() => expect(update).toHaveBeenCalledTimes(2));
    expect(update).toHaveBeenNthCalledWith(2, { prompt: { text: "Original A" } });
  } finally {
    release();
  }
});

it("keeps same-text restore intent through a held manual save and adopts server metadata", async () => {
  let app = {
    id: "app",
    prompt: { text: "Original A", description: "Previous provenance" }
  } as unknown as App;
  const old = {
    id: "old",
    text: "Manual B",
    description: "Historical marker",
    created_at: "2026-10-01T12:00:00Z",
    is_selected: false,
    user: { id: "user-1", email: "owner@example.se" }
  };
  api.GET.mockImplementation(async (path) => ({
    data: path.includes("/prompts/{id}") ? old : { items: [old] },
    response: new Response("{}")
  }));
  let release!: () => void;
  const held = new Promise<void>((resolve) => {
    release = resolve;
  });
  const view = renderInApp(<InstructionsSection app={app} />);
  update.mockImplementation(async (body) => {
    const prompt = (body as AppUpdate).prompt!;
    if (!prompt.description) await held;
    app = {
      ...app,
      prompt: { ...app.prompt!, text: prompt.text, description: prompt.description ?? "" }
    };
    view.rerender(<InstructionsSection app={app} />);
    return app;
  });
  const field = screen.getByRole("textbox", { name: "Prompt" });
  fireEvent.change(field, { target: { value: "Manual B" } });
  fireEvent.blur(field);
  await waitFor(() => expect(update).toHaveBeenCalledWith({ prompt: { text: "Manual B" } }));
  try {
    fireEvent.click(screen.getByRole("button", { name: "Visa prompthistorik" }));
    await screen.findByRole("button", { name: "Återställ denna version" });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Återställ denna version" }).getAttribute("aria-busy")
      ).toBeNull()
    );
    fireEvent.click(screen.getByRole("button", { name: "Återställ denna version" }));
    expect(update).toHaveBeenCalledTimes(1);
    await act(async () => {
      release();
    });
    await waitFor(() =>
      expect(update).toHaveBeenNthCalledWith(2, {
        prompt: { text: "Manual B", description: expect.stringMatching(/^Återställd prompt från /) }
      })
    );
    const restored = update.mock.results[1];
    assert(restored?.type === "return");
    await act(async () => {
      await restored.value;
    });
    app = { ...app, prompt: { ...app.prompt!, description: "External metadata" } };
    view.rerender(<InstructionsSection app={app} />);
    fireEvent.blur(field);
    fireEvent.change(field, { target: { value: "Uncommitted edit" } });
    fireEvent.change(field, { target: { value: "Manual B" } });
    await act(async () => {
      fireEvent.blur(field);
    });
    expect(update).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole("button", { name: "Visa prompthistorik" }));
    await screen.findByRole("button", { name: "Återställ denna version" });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Återställ denna version" }).getAttribute("aria-busy")
      ).toBeNull()
    );
    fireEvent.click(screen.getByRole("button", { name: "Återställ denna version" }));
    await waitFor(() =>
      expect(update).toHaveBeenNthCalledWith(3, {
        prompt: { text: "Manual B", description: expect.stringMatching(/^Återställd prompt från /) }
      })
    );
  } finally {
    release();
  }
});
