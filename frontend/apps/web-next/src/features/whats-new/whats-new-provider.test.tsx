// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { sessionKeys } from "@/lib/api/session";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const put = vi.hoisted(() => vi.fn());
const remove = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: { PUT: put, DELETE: remove } }));

import { latestRelease } from "@eneo/whats-new";
import { WhatsNewProvider, useWhatsNew } from "./whats-new-provider";

// The announcement is whatever the catalog's latest release is.
const latestVersion = latestRelease()!.version;

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

/** The backend's answer to a PUT: the whole state, one marker moved to the latest release. */
let answered = { seen_version: null as string | null, announced_version: null as string | null };

beforeEach(() => {
  answered = { seen_version: null, announced_version: null };
  put.mockImplementation((path: string) => {
    answered = path.endsWith("/seen/")
      ? { ...answered, seen_version: latestVersion }
      : { ...answered, announced_version: latestVersion };
    return Promise.resolve({ data: answered, response: new Response("{}", { status: 200 }) });
  });
});

/** The provider over the session's What's new markers (null: unavailable). */
function renderWithMarkers(
  state: { seen_version: string | null; announced_version: string | null } | null,
  appContext = testAppContext()
) {
  const queryClient = testQueryClient();
  queryClient.setQueryData(sessionKeys.whatsNew, state);
  return renderInApp(
    <WhatsNewProvider>
      <Probe />
    </WhatsNewProvider>,
    { queryClient, appContext }
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("What's new markers", () => {
  it("keeps the unseen dot after recording the one-time announcement", async () => {
    renderWithMarkers({ seen_version: null, announced_version: null });
    expect(screen.getByTestId("unseen").textContent).toBe("true");
    expect(screen.getByTestId("announcement").textContent).toBe(latestVersion);
    fireEvent.click(screen.getByText("Announced"));
    await waitFor(() => expect(screen.getByTestId("announcement").textContent).toBe("none"));
    expect(screen.getByTestId("unseen").textContent).toBe("true");
    fireEvent.click(screen.getByText("Seen"));
    await waitFor(() => expect(screen.getByTestId("unseen").textContent).toBe("false"));
  });

  it("announces and records an installed release candidate under its own version", async () => {
    const candidate = `${latestVersion}-rc.2`;
    renderWithMarkers(
      { seen_version: null, announced_version: null },
      testAppContext({ versions: { frontend: `v${candidate}` } })
    );
    expect(screen.getByTestId("announcement").textContent).toBe(candidate);
    fireEvent.click(screen.getByText("Announced"));
    fireEvent.click(screen.getByText("Seen"));
    await waitFor(() => expect(put).toHaveBeenCalledTimes(2));
    expect(put).toHaveBeenCalledWith("/api/v1/whats-new/announced/", {
      body: { version: candidate }
    });
    expect(put).toHaveBeenCalledWith("/api/v1/whats-new/seen/", { body: { version: candidate } });
  });

  it("does not treat an unavailable state endpoint as a first visit", () => {
    renderWithMarkers(null);
    expect(screen.getByTestId("unseen").textContent).toBe("false");
    expect(screen.getByTestId("announcement").textContent).toBe("none");
    fireEvent.click(screen.getByText("Seen"));
    fireEvent.click(screen.getByText("Announced"));
    expect(put).not.toHaveBeenCalled();
  });
});
