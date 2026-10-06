"use client";

import { ExpiringKeysNotification } from "@/features/api-keys/expiring-keys-notification";
import { JobIndicator } from "@/features/jobs/job-indicator";

/**
 * The job and expiring-key bells, in the same place in every navigation: the
 * SideNav header, the phone top bar and the drawer header (the only place on
 * phone chat routes, which have no top bar). Their popovers open toward
 * `alignment`: "start" from the left-hand SideNav, "end" near the right edge.
 */
export function NotificationBells({ alignment = "end" }: { alignment?: "start" | "end" }) {
  return (
    <>
      <JobIndicator alignment={alignment} />
      <ExpiringKeysNotification alignment={alignment} />
    </>
  );
}
