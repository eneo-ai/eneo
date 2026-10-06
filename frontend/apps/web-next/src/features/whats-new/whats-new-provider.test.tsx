// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const put = vi.hoisted(() => vi.fn());
const remove = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: { PUT: put, DELETE: remove } }));

import { WhatsNewProvider, useWhatsNew } from "./whats-new-provider";

function Probe() {
  const state = useWhatsNew();
  return (
    <div>
      <span data-testid="unseen">{String(state.hasUnseen)}</span>
      <span data-testid="announcement">{state.pendingRelease?.version ?? "none"}</span>
      <button onClick={() => void state.markLatestSeen()}>Seen</button>
      <button onClick={() => void state.markLatestAnnounced()}>Announced</button>
    </div>
  );
}

beforeEach(() => {
  put.mockImplementation((path: string) =>
    Promise.resolve({
      data: path.endsWith("/seen/") ? { seen_version: "2.2.0" } : { announced_version: "2.2.0" },
      response: new Response("{}", { status: 200 })
    })
  );
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("What's new markers", () => {
  it("keeps the unseen dot after recording the one-time announcement", async () => {
    render(
      <WhatsNewProvider enabled initialSeen={null} initialAnnounced={null}>
        <Probe />
      </WhatsNewProvider>
    );
    expect(screen.getByTestId("unseen").textContent).toBe("true");
    expect(screen.getByTestId("announcement").textContent).toBe("2.2.0");
    fireEvent.click(screen.getByText("Announced"));
    await waitFor(() => expect(screen.getByTestId("announcement").textContent).toBe("none"));
    expect(screen.getByTestId("unseen").textContent).toBe("true");
    fireEvent.click(screen.getByText("Seen"));
    await waitFor(() => expect(screen.getByTestId("unseen").textContent).toBe("false"));
  });

  it("does not treat an unavailable state endpoint as a first visit", () => {
    render(
      <WhatsNewProvider enabled initialSeen={undefined} initialAnnounced={undefined}>
        <Probe />
      </WhatsNewProvider>
    );
    expect(screen.getByTestId("unseen").textContent).toBe("false");
    expect(screen.getByTestId("announcement").textContent).toBe("none");
    fireEvent.click(screen.getByText("Seen"));
    fireEvent.click(screen.getByText("Announced"));
    expect(put).not.toHaveBeenCalled();
  });
});
