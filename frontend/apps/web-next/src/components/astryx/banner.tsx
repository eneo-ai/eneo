"use client";

import { Banner, type BannerProps } from "@astryxdesign/core/Banner";

/**
 * Astryx Banner without a live region of its own, for a notice about a state
 * that lasts (a failure that holds until someone fixes it) and is shown
 * whenever its page or tab is open. Astryx 0.6.4 makes an error or warning
 * banner role="alert", which a screen reader reads out assertively each time
 * it mounts: on every return to the tab. Announce what is new politely
 * instead (`useAnnounceChange`). A banner for something that just happened
 * (a list that failed to load) keeps Astryx's role.
 */
export function QuietBanner(props: Omit<BannerProps, "role">) {
  return <Banner {...props} role={undefined} />;
}
