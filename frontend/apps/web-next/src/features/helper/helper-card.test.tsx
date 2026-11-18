// @vitest-environment jsdom
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { Pencil } from "lucide-react";
import { afterEach, describe, expect, it } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { FieldBeforeAfter, HelperCardFrame, isLongText } from "./helper-card";

afterEach(cleanup);

function Card({ long }: { long: boolean }) {
  return (
    <HelperCardFrame
      label="Ändrade namnet"
      icon={<Pencil className="size-4" />}
      status={<span>Inte sparat</span>}
    >
      <ul>
        <FieldBeforeAfter
          label="Namn"
          long={long}
          before={(folded) => <span>{folded ? "före, ihopfällt" : "före, helt"}</span>}
          after={(folded) => <span>{folded ? "efter, ihopfällt" : "efter, helt"}</span>}
        />
      </ul>
    </HelperCardFrame>
  );
}

describe("The helper's card parts", () => {
  it("name the card by its title, with its status in the title row", () => {
    renderInApp(<Card long={false} />);

    const card = screen.getByRole("region", { name: "Ändrade namnet" });
    expect(card.querySelector("h3")?.textContent).toBe("Ändrade namnet");
    expect(screen.getByText("Inte sparat")).toBeTruthy();
    expect(screen.getByText("före, helt")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Visa hela" })).toBeNull();
  });

  it("fold a long value until Visa hela, and fold it again with Visa mindre", () => {
    renderInApp(<Card long />);

    expect(screen.getByText("före, ihopfällt")).toBeTruthy();
    expect(screen.getByText("efter, ihopfällt")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Visa hela" }));
    expect(screen.getByText("efter, helt")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Visa mindre" }));
    expect(screen.getByText("efter, ihopfällt")).toBeTruthy();
  });

  it("count a text as long by its characters or its lines", () => {
    expect(isLongText("kort")).toBe(false);
    expect(isLongText("x".repeat(201))).toBe(true);
    expect(isLongText("a\nb\nc\nd\ne")).toBe(true);
  });

  it("have no axe violations", async () => {
    const { container } = renderInApp(<Card long />);
    await expectNoAxeViolations(container);
  });
});
