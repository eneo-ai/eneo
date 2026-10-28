// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { MigrationHistoryPanel } from "./migration-history-panel";
import { MODEL_MIGRATION_HISTORY_KEY, type ModelMigrationHistory } from "./models";

vi.mock("@/lib/api/browser", () => ({ browserApi: { GET: vi.fn() } }));

const history: ModelMigrationHistory[] = [
  {
    id: "h1",
    from_model_name: "GPT-4",
    to_model_name: "GPT-4o",
    migrated_count: 12,
    status: "completed",
    initiated_by_id: "u1",
    initiated_by_name: "Anna Lind",
    completed_at: "2026-09-01T10:00:00Z",
    duration: 2500,
    migration_details: { assistants: 10, apps: 2, total: 12 },
    warnings: ["Target model lacks vision support"],
    model_type: "completion"
  },
  {
    id: "h2",
    from_model_name: "Whisper",
    to_model_name: "KB-Whisper",
    migrated_count: 0,
    status: "failed",
    initiated_by_id: "u2",
    initiated_by_name: "Per Berg",
    completed_at: "2026-08-01T10:00:00Z",
    error_message: "Timeout",
    model_type: "transcription"
  }
];

afterEach(cleanup);

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
  client.setQueryData(MODEL_MIGRATION_HISTORY_KEY, history);
  render(
    <NextIntlClientProvider locale="sv" messages={messages}>
      <QueryClientProvider client={client}>
        <MigrationHistoryPanel />
      </QueryClientProvider>
    </NextIntlClientProvider>
  );
}

it("lists migrations with a status label and a disclosure per row", async () => {
  renderPanel();
  const table = screen.getByRole("table", { name: "Migreringshistorik" });
  expect(within(table).getByText("Klar")).toBeTruthy();
  expect(within(table).getByText("Misslyckad")).toBeTruthy();

  const toggle = screen.getByRole("button", { name: "Detaljer för GPT-4 till GPT-4o" });
  expect(toggle.getAttribute("aria-expanded")).toBe("false");
  expect(toggle.getAttribute("aria-controls")).toBeNull();

  fireEvent.click(toggle);

  expect(toggle.getAttribute("aria-expanded")).toBe("true");
  const detail = document.getElementById(toggle.getAttribute("aria-controls")!);
  expect(detail?.textContent).toContain("Target model lacks vision support");
  expect(detail?.textContent).toContain("2.5s");

  await expectNoAxeViolations(document.body);
});

it("searches and announces how many migrations match", async () => {
  renderPanel();
  fireEvent.change(screen.getByRole("textbox", { name: "Sök i migreringshistoriken" }), {
    target: { value: "whisper" }
  });
  const table = screen.getByRole("table", { name: "Migreringshistorik" });
  expect(within(table).queryByText("GPT-4o")).toBeNull();
  expect(within(table).getByText("KB-Whisper")).toBeTruthy();
  // Through Astryx's persistent polite live region (WCAG 4.1.3).
  await waitFor(() =>
    expect(document.querySelector("[data-astryx-live-region='polite']")?.textContent).toBe(
      "1 migrering visas"
    )
  );
});

it("announces a failed read as an error with its retry, not as an empty status", async () => {
  const { browserApi } = await import("@/lib/api/browser");
  vi.mocked(browserApi.GET).mockResolvedValue({
    error: { message: "Boom", error_id: "8bc91e0a" },
    response: new Response(null, { status: 500 })
  } as never);
  const { renderInApp } = await import("@/test/render");
  renderInApp(<MigrationHistoryPanel />);

  const title = await screen.findByText("Det gick inte att ladda migrationshistoriken");
  const alert = title.closest<HTMLElement>('[role="alert"]');
  expect(alert).not.toBeNull();
  expect(title.closest('[role="status"]')).toBeNull();
  expect(
    within(alert!).getByRole("button", {
      name: "Försök igen: Det gick inte att ladda migrationshistoriken"
    })
  ).toBeTruthy();
});

it("keeps the focused retry button, busy, while a failed read is retried", async () => {
  const { browserApi } = await import("@/lib/api/browser");
  // The first read fails; the retry's requests stay in flight.
  let calls = 0;
  vi.mocked(browserApi.GET).mockImplementation((() => {
    calls += 1;
    return calls <= 2
      ? Promise.resolve({
          error: { message: "Boom" },
          response: new Response(null, { status: 500 })
        })
      : new Promise(() => {});
  }) as never);
  const { renderInApp } = await import("@/test/render");
  renderInApp(<MigrationHistoryPanel />);

  const retry = await screen.findByRole("button", {
    name: "Försök igen: Det gick inte att ladda migrationshistoriken"
  });
  retry.focus();
  fireEvent.click(retry);

  await waitFor(() => expect(retry.getAttribute("aria-busy")).toBe("true"));
  expect(retry.isConnected).toBe(true);
  expect(document.activeElement).toBe(retry);
  expect(screen.queryByText("Laddar...")).toBeNull();
});

it("keeps the migrations on screen when a refresh fails", async () => {
  const { browserApi } = await import("@/lib/api/browser");
  vi.mocked(browserApi.GET).mockResolvedValue({
    error: { message: "Boom" },
    response: new Response(null, { status: 500 })
  } as never);
  const { renderInApp, testQueryClient } = await import("@/test/render");
  const queryClient = testQueryClient();
  queryClient.setQueryData(MODEL_MIGRATION_HISTORY_KEY, history);
  renderInApp(<MigrationHistoryPanel />, { queryClient });
  expect(screen.getByRole("table", { name: "Migreringshistorik" })).toBeTruthy();

  await queryClient.refetchQueries({ queryKey: MODEL_MIGRATION_HISTORY_KEY });

  expect(
    await screen.findByText("Innehållet kunde inte uppdateras. Senast hämtade uppgifter visas.")
  ).toBeTruthy();
  expect(screen.getByRole("table", { name: "Migreringshistorik" })).toBeTruthy();
});
