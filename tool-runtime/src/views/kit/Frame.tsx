/// <reference lib="dom" />
import { useEffect, useRef, type ReactNode } from "react";
import { Divider } from "@astryxdesign/core/Divider";
import { Heading } from "@astryxdesign/core/Heading";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Theme } from "@astryxdesign/core/theme";
import { Toolbar } from "@astryxdesign/core/Toolbar";
import { neutralTheme } from "@astryxdesign/theme-neutral/built";
import { HostContext, pick, useViewHost, type Host } from "./host";
import { QuoteSelection } from "./Quote";
import { useSteadySelection } from "./selection";

const TEXTS = {
  sv: { expand: "Större vy", rows: "Rader" },
  en: { expand: "Larger view", rows: "Rows" },
};

// The theme's icon set has no glyph for a larger view; this is Lucide's, like the rest of it.
const expandIcon = (
  <svg
    width="16"
    height="16"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    <polyline points="15 3 21 3 21 9" />
    <polyline points="9 21 3 21 3 15" />
    <line x1="21" x2="14" y1="3" y2="10" />
    <line x1="3" x2="10" y1="21" y2="14" />
  </svg>
);

type FrameProps = {
  host: Host;
  /** Which view this is, for its own styles. */
  name: string;
  /** A view with nothing to show takes no room. */
  shown: boolean;
  /** Says what is shown, in one line. */
  title: string;
  /** Names the header for a reader who does not see it. */
  label: string;
  /** The view's own controls; the frame adds the larger view after them. */
  controls?: ReactNode;
  /** What the reader must know: banners, under the header. */
  notices?: ReactNode;
  /** Progress and the next step, under the content. */
  footer?: ReactNode;
  children: ReactNode;
};

/**
 * The frame every view is drawn in: a header that says what is shown and holds the controls,
 * notices under it, the view's content, and a footer when there is more to fetch or say. It
 * follows the host's theme, language and display mode, tells the host how tall it is, and
 * offers to quote what the reader selects in it. The host draws the border around it.
 */
export function ViewFrame(props: FrameProps) {
  const { host, shown } = props;
  const { app, context, connected } = host;
  const text = pick(context, TEXTS);
  const fullscreen = context.displayMode === "fullscreen";
  const root = useRef<HTMLDivElement>(null);
  useSteadySelection();

  useEffect(() => {
    document.documentElement.lang = context.locale ?? "sv";
    document.documentElement.dataset.mode = fullscreen ? "fullscreen" : "inline";
  }, [context.locale, fullscreen]);

  useEffect(() => {
    const element = root.current;
    if (!connected || !element) return;
    let reported = -1;
    const report = () => {
      const height = shown ? Math.ceil(element.getBoundingClientRect().height) : 0;
      if (height === reported) return;
      reported = height;
      void app.sendSizeChanged({ width: Math.ceil(window.innerWidth), height });
    };
    const observer = new ResizeObserver(report);
    observer.observe(element);
    report();
    return () => observer.disconnect();
  }, [app, connected, shown]);

  const canExpand = !fullscreen && context.availableDisplayModes?.includes("fullscreen");
  return (
    <HostContext value={host}>
      <Theme theme={neutralTheme} mode={context.theme === "dark" ? "dark" : "light"}>
        <div ref={root} className="eneo-view" data-view={props.name} hidden={!shown}>
          <Toolbar
            label={props.label}
            dividers={["bottom"]}
            startContent={<Heading level={4}>{props.title}</Heading>}
            endContent={
              <>
                {props.controls}
                {canExpand && (
                  <>
                    {props.controls ? <Divider orientation="vertical" /> : null}
                    <IconButton
                      variant="ghost"
                      label={text.expand}
                      tooltip={text.expand}
                      icon={expandIcon}
                      onClick={() =>
                        void app.requestDisplayMode({ mode: "fullscreen" }).catch(() => undefined)
                      }
                    />
                  </>
                )}
              </>
            }
          />
          {props.notices}
          {props.children}
          {props.footer}
          <QuoteSelection />
        </div>
      </Theme>
    </HostContext>
  );
}

/**
 * Where a table's rows scroll, in both directions, under headings that stay in place. Given
 * to an Astryx Table as its scroll wrapper.
 */
export function TableRows(props: {
  children: ReactNode;
  beforeTable?: ReactNode;
  afterTable?: ReactNode;
}) {
  const text = pick(useViewHost().context, TEXTS);
  return (
    // Focusable, so the rows can be scrolled from the keyboard.
    <div className="eneo-rows" role="region" aria-label={text.rows} tabIndex={0}>
      {props.beforeTable}
      {props.children}
      {props.afterTable}
    </div>
  );
}
