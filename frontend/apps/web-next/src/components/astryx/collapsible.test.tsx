// @vitest-environment jsdom
import type { CollapsibleProps } from "@astryxdesign/core/Collapsible";
import { fireEvent, screen } from "@testing-library/react";
import { useRef, type ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { AnimatedLayoutScope, Collapsible, StillLayoutScope } from "./collapsible";

// The handle each Astryx Collapsible was given, by its trigger; it still renders.
const handles = vi.hoisted(() => new Map<unknown, unknown>());
vi.mock("@astryxdesign/core/Collapsible", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@astryxdesign/core/Collapsible")>();
  return {
    ...actual,
    Collapsible: (props: CollapsibleProps) => {
      handles.set(props.trigger, props.animatedLayout);
      return <actual.Collapsible {...props} />;
    }
  };
});

beforeEach(() => handles.clear());

function Scope({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  return (
    <div ref={ref}>
      <AnimatedLayoutScope containerRef={ref}>{children}</AnimatedLayoutScope>
    </div>
  );
}

it("gives every Collapsible in a scope that scope's handle, the nearest one when nested", () => {
  renderInApp(
    <>
      <Collapsible trigger="Utanför">a</Collapsible>
      <Scope>
        <Collapsible trigger="Sidan">b</Collapsible>
        <Collapsible trigger="Sidan igen">c</Collapsible>
        <Scope>
          <Collapsible trigger="Konversationen">d</Collapsible>
        </Scope>
      </Scope>
    </>
  );

  expect(handles.get("Utanför")).toBeUndefined();
  expect(handles.get("Sidan")).toBeTypeOf("object");
  expect(handles.get("Sidan igen")).toBe(handles.get("Sidan"));
  expect(handles.get("Konversationen")).toBeTypeOf("object");
  expect(handles.get("Konversationen")).not.toBe(handles.get("Sidan"));
});

it("gives no handle inside a still scope, even within a page scope", () => {
  renderInApp(
    <Scope>
      <StillLayoutScope>
        <Collapsible trigger="I samtalet">a</Collapsible>
      </StillLayoutScope>
    </Scope>
  );

  expect(handles.get("I samtalet")).toBeUndefined();
});

it("still opens and closes in a scope where nothing can animate", () => {
  renderInApp(
    <Scope>
      <Collapsible trigger="Detaljer" defaultIsOpen={false}>
        <p>Innehåll</p>
      </Collapsible>
    </Scope>
  );
  const trigger = screen.getByRole("button", { name: "Detaljer" });
  const content = document.getElementById(trigger.getAttribute("aria-controls")!)!;

  fireEvent.click(trigger);
  expect(trigger.getAttribute("aria-expanded")).toBe("true");
  expect(content.textContent).toBe("Innehåll");

  // Without Web Animations the close lands at once: the content is not held
  // back, out of reach, for an exit that never plays.
  fireEvent.click(trigger);
  expect(trigger.getAttribute("aria-expanded")).toBe("false");
  expect(content.hasAttribute("inert")).toBe(false);
  expect(content.style.marginBlockEnd).toBe("");
});
