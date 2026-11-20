import type { AppRun } from "@eneo/eneo-js";
import { render } from "vitest-browser-svelte";
import { page } from "vitest/browser";
import { afterEach, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import { readable } from "svelte/store";
import SpaceResultPage from "../../../../../spaces/[spaceId]/apps/[appId]/results/[resultId]/+page.svelte";
import ResultPage from "./+page.svelte";
import type { PageData } from "./$types";
import type { PageData as SpaceResultData } from "../../../../../spaces/[spaceId]/apps/[appId]/results/[resultId]/$types";

const api = vi.hoisted(() => ({
  get: vi.fn(),
  sign: vi.fn(),
  subscribe: vi.fn(() => () => {})
}));
vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({
    apps: { runs: { get: api.get } },
    files: { generateSignedUrl: api.sign }
  })
}));
vi.mock("$lib/core/EneoSocket", () => ({ getEneoSocket: () => ({ subscribe: api.subscribe }) }));
vi.mock("$lib/features/attachments/AttachmentUrlService.svelte.js", () => ({
  getAttachmentUrlService: () => ({ getUrl: () => "/original.wav" })
}));

vi.mock("$app/state", () => ({ page: { state: {}, url: new URL("http://localhost/results") } }));
vi.mock("$app/navigation", async (original) => ({
  ...(await original()),
  afterNavigate: vi.fn(),
  beforeNavigate: vi.fn(),
  onNavigate: vi.fn(),
  replaceState: vi.fn()
}));
vi.mock("$lib/features/spaces/SpacesManager", () => ({
  getSpacesManager: () => ({ state: { currentSpace: readable({ routeId: "space" }) } })
}));

const recording = { id: "audio", name: "meeting.wav", mimetype: "audio/wav", size: 1200 };
function run(status: AppRun["status"], transcription?: string): AppRun {
  return {
    id: "run",
    input: { files: [{ ...recording, transcription }], text: null },
    created_at: "2026-10-10T10:00:00Z",
    finished_at: null,
    output: status === "complete" ? "Summary" : null,
    skill_provenance: [],
    status,
    user: { id: "owner", email: "owner@example.org" }
  };
}
function show(result: AppRun) {
  return render(ResultPage, { data: { app: { id: "app", name: "Meeting" }, result } as PageData });
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

it("updates an open result after a missed completion event and a transient read failure", async () => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
  api.get
    .mockRejectedValueOnce(new TypeError("Offline"))
    .mockResolvedValue(run("complete", "Meeting transcript"));
  const view = show(run("in progress"));
  await vi.advanceTimersByTimeAsync(60_000);
  expect(view.container.textContent).toContain("Summary");
  const reads = api.get.mock.calls.length;
  await vi.advanceTimersByTimeAsync(60_000);
  expect(api.get).toHaveBeenCalledTimes(reads);
});

it.each([
  ["dashboard", "in progress"],
  ["space", "in progress"],
  ["dashboard", "failed"],
  ["space", "failed"]
] as const)(
  "downloads the saved transcript from %s while the summary is %s",
  async (surface, status) => {
    const write = vi.fn(async (_blob: Blob) => {});
    vi.stubGlobal("showSaveFilePicker", async () => ({
      createWritable: async () => ({ write, close: async () => {} })
    }));
    api.sign.mockResolvedValue({ url: "/original.wav" });
    const saved = run(status, "Mötesanteckningar");
    const result = status === "in progress" ? run(status) : saved;
    if (status === "in progress") {
      vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
      api.get.mockResolvedValueOnce(result);
    }
    api.get.mockResolvedValue(saved);
    if (surface === "dashboard") {
      show(result);
    } else {
      const data = {
        currentSpace: { name: "Space", personal: false },
        app: { id: "app", name: "Meeting" },
        result
      } satisfies {
        currentSpace: Pick<SpaceResultData["currentSpace"], "name" | "personal">;
        app: Pick<SpaceResultData["app"], "id" | "name">;
        result: AppRun;
      };
      render(SpaceResultPage, { data: data as SpaceResultData });
    }
    const transcription = page.getByRole(surface === "dashboard" ? "button" : "tab", {
      name: m.transcription(),
      exact: true
    });
    if (status === "in progress") {
      await vi.waitFor(() => expect(api.get).toHaveBeenCalledTimes(1));
      expect(transcription.query()).toBeNull();
      await vi.advanceTimersByTimeAsync(15_000);
      expect(api.get).toHaveBeenCalledTimes(2);
    }
    await transcription.click();
    await page
      .getByRole("button", {
        name: m.download_type_raw_text({ type: m.transcription().toLocaleLowerCase() })
      })
      .click();
    await vi.waitFor(() => expect(write).toHaveBeenCalledTimes(1));
    expect(await write.mock.calls[0][0].text()).toBe("Mötesanteckningar");
  }
);

it("downloads the input recording while the job is still queued", async () => {
  api.get.mockResolvedValue(run("queued"));
  const originalUrl = window.location.href;
  const signed = new URL(originalUrl);
  signed.hash = "signed-recording";
  api.sign.mockResolvedValue({ url: signed.href });
  try {
    show(run("queued"));
    await page.getByRole("button", { name: new RegExp(m.download() + ".*meeting.wav") }).click();
    expect(api.sign).toHaveBeenCalledWith({
      fileId: recording.id,
      contentDisposition: "attachment"
    });
    await vi.waitFor(() => expect(window.location.href).toBe(signed.href));
  } finally {
    history.replaceState(history.state, "", originalUrl);
  }
});
