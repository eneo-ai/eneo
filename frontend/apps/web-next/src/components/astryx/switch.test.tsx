// @vitest-environment jsdom
import { fireEvent, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { Switch } from "./switch";

it("is Astryx's switch, without the busy props that announce an English 'Loading'", () => {
  const onChange = vi.fn();
  renderInApp(<Switch label="Aktiv" value={false} onChange={onChange} />);

  fireEvent.click(screen.getByRole("switch", { name: "Aktiv" }));
  expect(onChange.mock.calls[0]?.[0]).toBe(true);

  // Type-level: `bun run check` fails if these props come back.
  // @ts-expect-error isLoading is left out on purpose
  void (<Switch label="Aktiv" value={false} onChange={onChange} isLoading />);
  // @ts-expect-error changeAction is left out on purpose
  void (<Switch label="Aktiv" value={false} onChange={onChange} changeAction={async () => {}} />);
});
