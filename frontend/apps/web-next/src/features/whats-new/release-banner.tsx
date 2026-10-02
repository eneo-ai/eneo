"use client";

import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Link } from "@astryxdesign/core/Link";
import { visibleEntries, type Release } from "@eneo/whats-new";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useAppContext } from "@/components/providers/app-context";
import { toast } from "@/lib/toast";
import { shouldShowAnnouncement, tourEntries } from "./release-model";
import { useOptionalTour } from "./tour-provider";
import { useOptionalWhatsNew } from "./whats-new-provider";

/**
 * The one-time release notice: a dismissible banner above the start page's
 * composer the first time a user is here after a release (it is recorded as
 * announced when it mounts; the unseen dot in the account menu stays until
 * the Nyheter page is opened). It never blocks the page.
 */
export function WhatsNewBanner() {
  const whatsNew = useOptionalWhatsNew();
  const tour = useOptionalTour();
  if (!whatsNew || !tour) return null;
  return (
    <ReleaseBanner
      pendingRelease={whatsNew.pendingRelease ?? null}
      markLatestAnnounced={whatsNew.markLatestAnnounced}
      tour={tour}
    />
  );
}

function ReleaseBanner({
  pendingRelease,
  markLatestAnnounced,
  tour
}: {
  pendingRelease: Release | null;
  markLatestAnnounced: () => Promise<void>;
  tour: NonNullable<ReturnType<typeof useOptionalTour>>;
}) {
  const t = useTranslations();
  const router = useRouter();
  const { user, can } = useAppContext();
  const isAdmin = can("admin");
  // Captured once: recording the release as announced clears pendingRelease,
  // and the banner must stay until the user leaves or dismisses it.
  const [release] = useState<Release | null>(() =>
    pendingRelease &&
    visibleEntries(pendingRelease, isAdmin).length > 0 &&
    shouldShowAnnouncement(pendingRelease, user.created_at)
      ? pendingRelease
      : null
  );
  const [open, setOpen] = useState(release !== null);
  const announced = useRef<string | null>(null);

  useEffect(() => {
    if (!release || announced.current === release.version) return;
    announced.current = release.version;
    void markLatestAnnounced();
  }, [release, markLatestAnnounced]);

  if (!release || !open) return null;
  const entries = visibleEntries(release, isAdmin);
  const steps = tourEntries(release, isAdmin);

  async function startTour() {
    if (tour.running) return;
    setOpen(false);
    try {
      const outcome = await tour.start(steps, release!.version);
      if (outcome === "unavailable") {
        toast.info(t("whats_new_show_me_unavailable"));
        router.push("/whats-new");
      }
    } catch {
      toast.error(t("whats_new_tour_failed"));
    }
  }

  return (
    <div className="w-full">
      <Banner
        status="info"
        title={t("whats_new_announcement_heading")}
        description={t("whats_new_banner_description", { count: entries.length })}
        isDismissable
        dismissLabel={t("whats_new_banner_dismiss")}
        onDismiss={() => setOpen(false)}
        endContent={
          <span className="flex flex-wrap items-center gap-x-4 gap-y-2">
            {steps.length > 0 && (
              <Button
                variant="primary"
                size="sm"
                label={t("whats_new_announcement_tour")}
                // The banner closes as the tour starts; a press while one runs is ignored.
                aria-busy={tour.running || undefined}
                onClick={() => void startTour()}
              />
            )}
            <Link href="/whats-new" hasUnderline>
              {t("whats_new_announcement_all", { count: entries.length })}
            </Link>
          </span>
        }
      />
    </div>
  );
}
