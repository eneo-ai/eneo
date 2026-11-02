import { Banner, type BannerProps } from "@astryxdesign/core/Banner";

/**
 * Astryx Banner without a live region, for a notice about a state that lasts
 * and is shown whenever its page or tab is open. Since Astryx 0.7 no Banner is
 * a live region, so this is a plain Banner; announce what is new politely
 * (`useAnnounceChange`).
 */
export function QuietBanner(props: Omit<BannerProps, "role">) {
  return <Banner {...props} role={undefined} />;
}

/**
 * Astryx Banner for an outcome that just happened (a list that failed to load,
 * a save that failed). Astryx 0.7 stopped deriving a live-region role from the
 * status; this opts back in, as Astryx documents: an error or warning is an
 * alert, other statuses a status (WCAG 4.1.3).
 */
export function AnnouncedBanner(props: Omit<BannerProps, "role">) {
  const urgent = props.status === "error" || props.status === "warning";
  return <Banner {...props} role={urgent ? "alert" : "status"} />;
}
