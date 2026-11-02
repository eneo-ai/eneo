// @vitest-environment jsdom
import { act, cleanup, screen } from "@testing-library/react";
import { useRef } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { renderInApp } from "@/test/render";
import { reportResize } from "@/test/setup-dom";
import { useElementWidth } from "./use-element-width";

afterEach(cleanup);

/** How often what the measured element holds renders (the conversation, in the chat). */
let renders = 0;

function Content() {
  renders += 1;
  return null;
}

function Measured({ select }: { select?: (width: number) => unknown }) {
  const ref = useRef<HTMLDivElement>(null);
  const value = useElementWidth(ref, select);
  return (
    <div ref={ref} data-testid="box">
      {JSON.stringify(value)}
      <Content />
    </div>
  );
}

const resize = (width: number) =>
  act(() => reportResize(screen.getByTestId("box"), { width, height: 100 }));

describe("useElementWidth", () => {
  it("is unknown until measured, then follows the element", () => {
    renderInApp(<Measured />);
    expect(screen.getByTestId("box").textContent).toBe("null");
    resize(908);
    expect(screen.getByTestId("box").textContent).toBe("908");
  });

  it("keeps the last width while the element is hidden", () => {
    renderInApp(<Measured />);
    resize(908);
    resize(0);
    expect(screen.getByTestId("box").textContent).toBe("908");
  });

  it("renders what it holds again only when what the caller selects changes", () => {
    renderInApp(<Measured select={(width) => width >= 800} />);
    resize(900);
    const before = renders;
    resize(950);
    resize(1000);
    expect(renders).toBe(before);
    resize(700);
    expect(screen.getByTestId("box").textContent).toBe("false");
  });
});
