// @vitest-environment jsdom
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp, testQueryClient } from "@/test/render";
import { AppDetail } from "./app-detail";
import { makeSpace } from "@/features/spaces/testing/space-fixture";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", () => ({
  useSpace: () => ({ routeId: "space-1", space: makeSpace() })
}));
vi.mock("./results/results-table", () => ({ ResultsTable: () => <p>Resultatvy</p> }));
// A run view with state of its own, as the real one has (the typed text and its uploads).
vi.mock("./run/run-view", () => ({
  RunView: () => {
    const [text, setText] = useState("");
    return <textarea aria-label="Fråga" value={text} onChange={(e) => setText(e.target.value)} />;
  }
}));
afterEach(cleanup);

it("keeps the run form mounted and its entered text while Resultat is looked at", () => {
  const queryClient = testQueryClient();
  queryClient.setQueryData(["apps", "app-1"], { id: "app-1", name: "Protokoll", permissions: [] });
  renderInApp(<AppDetail appId="app-1" />, { queryClient, route: "/spaces/space-1/apps/app-1" });

  fireEvent.change(screen.getByLabelText("Fråga"), {
    target: { value: "Sammanfatta protokollet" }
  });
  fireEvent.mouseDown(screen.getByRole("tab", { name: "Resultat" }));
  fireEvent.click(screen.getByRole("tab", { name: "Resultat" }));
  fireEvent.mouseDown(screen.getByRole("tab", { name: "Kör" }));
  fireEvent.click(screen.getByRole("tab", { name: "Kör" }));

  // The run view never unmounted: its text (and the files it uploaded, which it
  // deletes on unmount) are still there.
  expect((screen.getByLabelText("Fråga") as HTMLTextAreaElement).value).toBe(
    "Sammanfatta protokollet"
  );
});
