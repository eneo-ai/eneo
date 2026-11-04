import { useSpaceSegments } from "@/lib/navigation";
import { PAGE_COLUMN } from "@/components/composites/page-frame";
import { usePhoneScreen, useTouchTablet } from "@/lib/hooks/use-media-match";
import { ClassificationToken } from "@/components/composites/classification-token";
import { cn } from "@/lib/utils";
import { useSpaceDisplayName } from "../space-display-name";
import { useSpace } from "../use-space";
import { Heading } from "@astryxdesign/core/Heading";
import { lazy, Suspense } from "react";
import { SpacePhoneHeader } from "./space-phone-header";
import { spaceRoute, type SpaceRoute } from "./space-sections";

/**
 * A tablet's space header, loaded on a tablet only: its code (the add-member
 * dialog among it) stays out of a computer's and a phone's pages. The app
 * shell starts loading it as soon as it knows it runs on a tablet; until it
 * is there, the space's name is the page's h1 for assistive technology.
 */
const SpaceHeader = lazy(() =>
  import("./space-header").then((module) => ({ default: module.SpaceHeader }))
);

/** The header's h1 while it loads: on a tab's own page only, as the header has it. */
function SpaceHeaderFallback({ route }: { route: Extract<SpaceRoute, { kind: "page" }> }) {
  const name = useSpaceDisplayName();
  if (!route.isSectionRoot) return null;
  return (
    <Heading level={1} className="sr-only">
      {name}
    </Heading>
  );
}

/**
 * Chrome around every route of one space. The chat renders full-bleed (it has
 * its own header and pins its composer to the bottom), and so does an editor
 * (assistant, app, group chat): its sticky header carries the breadcrumb back
 * to the space and the tab, the save state and the actions, so stacking the
 * space header and tabs on top would only push its own section tabs off the
 * screen. Every other page gets the space header and tabs above it and
 * scrolls with them in the app shell's page panel, `main#main-content`, the
 * one scroll container: the header scrolls away (nothing sticky covers
 * focus), Page Down works right after the skip link, and the page reflows at
 * 320 px / 400 %.
 *
 * Pages sit in a `p-6` inset (16 px on a phone), in the pages' shared column
 * (`PAGE_COLUMN`), which the header's content shares too. A page that spans
 * the frame edge to edge, such as the settings with their sticky header,
 * marks its root element with `data-space-full-bleed` and the inset and the
 * column go away.
 *
 * A phone, held either way, gets SpacePhoneHeader instead of the header
 * (decision 24): a phone turned sideways has too little height for the
 * breadcrumb, the title and seven tabs.
 *
 * A tablet keeps the space's header with its tabs (SpaceHeader, #1328): its
 * SideNav lists every space, not the one the page is in.
 *
 * Beside the full sidebar its heading names the space. Its icon rail (an iPad
 * either way, a small laptop) has room for the space's mark only, so a
 * section page then names the space and its class above its title.
 */
export function SpaceFrame({ children }: { children: React.ReactNode }) {
  const segments = useSpaceSegments();
  const route = spaceRoute(segments);
  const phone = usePhoneScreen();
  const tablet = useTouchTablet();

  if (route.kind === "chat") {
    return <div className="flex min-h-0 min-w-0 flex-1 flex-col">{children}</div>;
  }

  if (route.kind === "editor") {
    return <div className="flex min-w-0 flex-1 flex-col">{children}</div>;
  }

  if (route.kind === "workspace") {
    return <div className="flex min-w-0 flex-1 flex-col lg:min-h-0">{children}</div>;
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      {phone ? (
        <SpacePhoneHeader route={route} segments={segments} />
      ) : tablet ? (
        <Suspense fallback={<SpaceHeaderFallback route={route} />}>
          <SpaceHeader route={route} />
        </Suspense>
      ) : null}
      <div className="wide:p-6 flex min-w-0 flex-1 flex-col p-4 has-[[data-space-full-bleed]]:p-0">
        <div
          className={cn(
            PAGE_COLUMN,
            "flex min-w-0 flex-1 flex-col has-[[data-space-full-bleed]]:max-w-none"
          )}
        >
          {!phone && !tablet && route.section !== "overview" ? <SpaceEyebrow /> : null}
          {children}
        </div>
      </div>
    </div>
  );
}

/**
 * Heading levels for a space page's own header: beside the sidebar its title
 * is the page's h1, as in Svelte's page bar; on a phone or a tablet the
 * space's header holds the h1 (its name) and the title is an h2. `sub` is the
 * level below it.
 */
export function useSectionHeadingLevels(): { title: 1 | 2; sub: 2 | 3 } {
  const phone = usePhoneScreen();
  const tablet = useTouchTablet();
  return phone || tablet ? { title: 2, sub: 3 } : { title: 1, sub: 2 };
}

/**
 * The space's name and security class above a section's title, shown only
 * while the shell marks the sidebar as its icon rail (`data-side-nav-rail`).
 * Not on Översikt, which names the space itself.
 */
function SpaceEyebrow() {
  const { space } = useSpace();
  const name = useSpaceDisplayName();
  return (
    <p
      data-space-eyebrow=""
      className="text-ax-text-secondary mb-2 hidden min-w-0 items-center gap-2 text-sm group-has-[[data-side-nav-rail]]/shell:flex"
    >
      <span className="truncate">{name}</span>
      <ClassificationToken variant="inline" name={space.security_classification?.name} />
    </p>
  );
}
