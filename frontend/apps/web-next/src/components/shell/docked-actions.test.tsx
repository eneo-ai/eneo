// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { DockedActions } from "./docked-actions";

it("gives way to the keyboard on a short screen while the page's field has focus", () => {
  // A phone turned sideways has about 200 px left with the keyboard up: the
  // bar would cover the field being typed in. jsdom applies no CSS, so the
  // class is what is checked; it holds the `short:` and `group/shell` rule.
  render(
    <DockedActions label="Åtgärder">
      <button type="button">Kör appen</button>
    </DockedActions>
  );
  expect(screen.getByRole("group", { name: "Åtgärder" }).className).toContain(
    "phone:short:pointer-coarse:group-has-[main_:is(input:not([type=checkbox],[type=radio],[type=file],[type=range],[type=button],[type=submit]),textarea,[contenteditable=true]):focus]/shell:invisible"
  );
});
