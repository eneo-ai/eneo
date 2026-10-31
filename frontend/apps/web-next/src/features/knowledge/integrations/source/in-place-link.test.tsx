// @vitest-environment jsdom
import { Button } from "@astryxdesign/core/Button";
import { Link } from "@astryxdesign/core/Link";
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { createTranslator } from "use-intl";
import { afterEach, describe, expect, it, vi } from "vitest";
import sv from "@/lib/i18n/messages/sv.json";
import { renderInApp } from "@/test/render";
import type { IntegrationKnowledge } from "../../knowledge";
import { buildSourceProblems } from "../source-problems";
import { inPlaceLink, SamePageLink } from "@/components/composites/in-place-link";
import { ProblemsView } from "./problems-view";

/** The props the app link gets, Astryx's links included (the app's LinkProvider uses the app link). */
const rendered = vi.hoisted(() => [] as Record<string, unknown>[]);
vi.mock("@/lib/link", async () => {
  const { Link } = await import("@/test/navigation");
  const { createElement } = await import("react");
  return {
    default: (props: Record<string, unknown>) => {
      rendered.push(props);
      return createElement(Link, props as unknown as Parameters<typeof Link>[0]);
    }
  };
});
vi.mock("@/lib/navigation", () => import("@/test/navigation"));

afterEach(() => {
  cleanup();
  rendered.length = 0;
});

const HREF = "/spaces/space-1/knowledge/integrations/wrapper/w1?tab=problems";
const propsFor = (href: string) => rendered.filter((props) => props.href === href);

describe("inPlaceLink", () => {
  it("handles a plain click itself and leaves any other click to the browser", () => {
    const go = vi.fn();
    renderInApp(<a {...inPlaceLink(HREF, go)}>Problem</a>);
    const link = screen.getByRole("link", { name: "Problem" });

    expect(fireEvent.click(link)).toBe(false);
    expect(go).toHaveBeenCalledTimes(1);

    for (const click of [
      { ctrlKey: true },
      { metaKey: true },
      { shiftKey: true },
      { altKey: true },
      { button: 1 }
    ]) {
      let prevented: boolean | undefined;
      // Reads the click as it leaves the page, then stops jsdom's navigation.
      const record = (event: Event) => {
        prevented = event.defaultPrevented;
        event.preventDefault();
      };
      document.addEventListener("click", record);
      fireEvent.click(link, click);
      document.removeEventListener("click", record);
      expect(prevented).toBe(false);
    }
    expect(go).toHaveBeenCalledTimes(1);
  });
});

describe("SamePageLink", () => {
  it("renders Astryx's links and buttons through the app link without prefetching", () => {
    renderInApp(
      <>
        <Link href={HREF} as={SamePageLink}>
          Öppna Mallar
        </Link>
        <Button label="Visa problem" href={HREF} as={SamePageLink} />
        <Link href="/spaces/space-1/overview">Översikt</Link>
      </>
    );

    expect(propsFor(HREF).map((props) => props.prefetch)).toEqual([false, false]);
    // An ordinary link keeps the app link's default.
    expect(propsFor("/spaces/space-1/overview").map((props) => props.prefetch)).toEqual([
      undefined
    ]);
    expect(screen.getByRole("link", { name: "Visa problem" }).getAttribute("href")).toBe(HREF);
    // Astryx hands the target over as `to` too; it is not left on the anchor.
    expect(document.querySelector("a[to]")).toBeNull();
  });

  it("is what the problems' folder links use", () => {
    const t = createTranslator({ locale: "sv", messages: sv as Record<string, string> });
    const failed = (id: string, name: string) =>
      ({
        id,
        name,
        folder_path: `/${name}`,
        metadata: { size: 0, last_sync_status: "error", last_sync_error: "Graph timeout" }
      }) as IntegrationKnowledge;
    const items = [failed("i1", "Mallar"), failed("i2", "Protokoll")];
    renderInApp(
      <ProblemsView
        problems={buildSourceProblems(items, { i1: null, i2: null }, t)}
        isAdmin={false}
        adminIntegrationsUrl="https://eneo.example.se/admin/integrations"
        folderLink={(id) => inPlaceLink(`/source?folder=${id}`, () => {})}
        showFolders
        onRetry={() => {}}
      />
    );

    expect(screen.getByRole("link", { name: "Öppna /Mallar" })).toBeTruthy();
    for (const id of ["i1", "i2"]) {
      expect(propsFor(`/source?folder=${id}`).map((props) => props.prefetch)).toEqual([false]);
    }
  });
});
