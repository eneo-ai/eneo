// @vitest-environment jsdom
import { Link } from "@astryxdesign/core/Link";
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderInApp } from "@/test/render";

describe("AstryxProvider", () => {
  it("renders Astryx links with next/link and without Astryx's router prop `to`", () => {
    renderInApp(<Link href="/spaces/list">Ytor</Link>);

    const link = screen.getByRole("link", { name: "Ytor" });
    expect(link.getAttribute("href")).toBe("/spaces/list");
    expect(link.hasAttribute("to")).toBe(false);
  });
});
