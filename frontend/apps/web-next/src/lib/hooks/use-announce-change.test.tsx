// @vitest-environment jsdom
import { cleanup, waitFor } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { renderInApp } from "@/test/render";
import { useAnnounceChange } from "./use-announce-change";

afterEach(cleanup);

/** What Astryx's polite live region has said (useAnnounce). */
const announced = () =>
  [...document.querySelectorAll("[aria-live]")].map((region) => region.textContent).join(" ");

function Notice({ message, state }: { message: string; state: boolean }) {
  useAnnounceChange(message, state);
  return null;
}

it("says a change of state, not the same state in other words", async () => {
  const { rerender } = renderInApp(<Notice message="Du är uppkopplad" state />);
  // The same state in another language: nothing to say.
  rerender(<Notice message="You're back online" state />);
  rerender(<Notice message="You're offline" state={false} />);
  await waitFor(() => expect(announced()).toContain("You're offline"));
  expect(announced()).not.toContain("back online");
});
