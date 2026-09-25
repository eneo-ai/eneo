"use client";

import { visibleEntries } from "@eneo/whats-new";
import type { Locale, Release } from "@eneo/whats-new";
import { ArrowRight, Sparkles } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useAppContext } from "@/components/providers/app-context";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { shouldShowAnnouncement, tourEntries } from "./release-model";
import { useTour } from "./tour-provider";
import { useWhatsNew } from "./whats-new-provider";

export function WhatsNewAnnouncement() {
  const t = useTranslations();
  const locale = useLocale() as Locale;
  const router = useRouter();
  const { user, can } = useAppContext();
  const { pendingRelease, markLatestAnnounced } = useWhatsNew();
  const { start, running } = useTour();
  const isAdmin = can("admin");
  const [release] = useState<Release | null>(() =>
    pendingRelease &&
    visibleEntries(pendingRelease, isAdmin).length > 0 &&
    shouldShowAnnouncement(pendingRelease, user.created_at)
      ? pendingRelease
      : null
  );
  const [open, setOpen] = useState(release !== null);
  const announced = useRef<string | null>(null);
  const entries = release ? visibleEntries(release, isAdmin) : [];
  const steps = release ? tourEntries(release, isAdmin) : [];

  useEffect(() => {
    if (!pendingRelease || announced.current === pendingRelease.version) return;
    if (visibleEntries(pendingRelease, isAdmin).length === 0) return;
    announced.current = pendingRelease.version;
    void markLatestAnnounced();
  }, [pendingRelease, isAdmin, markLatestAnnounced]);

  function openPage() {
    setOpen(false);
    router.push("/whats-new");
  }

  async function primary() {
    if (!release || steps.length === 0) return openPage();
    setOpen(false);
    try {
      const outcome = await start(steps, release.version);
      if (outcome === "unavailable") {
        toast.info(t("whats_new_show_me_unavailable"));
        openPage();
      }
    } catch {
      toast.error(t("whats_new_tour_failed"));
    }
  }

  if (!release) return null;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto p-0 sm:max-w-3xl">
        <div className="grid md:min-h-[460px] md:grid-cols-[260px_minmax(0,1fr)]">
          <div className="bg-foreground text-background flex flex-col gap-5 p-7">
            <Sparkles className="size-7" aria-hidden="true" />
            <DialogHeader className="text-left">
              <span className="text-xs font-semibold tracking-wide uppercase opacity-75">
                {t("whats_new_release", { version: release.version })}
              </span>
              <DialogTitle className="text-background text-2xl leading-tight">
                {t("whats_new_announcement_heading")}
              </DialogTitle>
              <DialogDescription className="text-background/85 leading-relaxed">
                {t("whats_new_announcement_intro_count", { count: entries.length })}
              </DialogDescription>
            </DialogHeader>
            <div className="mt-auto space-y-2 pt-4">
              <Button
                className="bg-background text-foreground hover:bg-background/90 w-full"
                size="lg"
                disabled={running}
                onClick={() => void primary()}
              >
                {t(steps.length ? "whats_new_announcement_tour" : "whats_new_announcement_action")}
                <ArrowRight className="size-4" />
              </Button>
              <Button
                variant="ghost"
                size="lg"
                className="text-background hover:bg-background/10 hover:text-background w-full"
                onClick={() => setOpen(false)}
              >
                {t("whats_new_announcement_later")}
              </Button>
            </div>
          </div>
          <div className="flex flex-col gap-4 px-6 pt-12 pb-6">
            <ul
              className="grid gap-3 sm:grid-cols-2"
              aria-label={t("whats_new_announcement_list_label")}
            >
              {entries.slice(0, 4).map((entry) => (
                <li key={entry.id} className="flex flex-col gap-2 rounded-lg border p-4">
                  <div className="flex items-center justify-between gap-2">
                    <Sparkles className="text-primary size-4" aria-hidden="true" />
                    <Badge variant="outline">{t(`whats_new_type_${entry.type}`)}</Badge>
                  </div>
                  <h3 className="text-sm font-semibold">{entry.title[locale] ?? entry.title.en}</h3>
                  <p className="text-muted-foreground line-clamp-4 text-xs leading-relaxed">
                    {entry.body[locale] ?? entry.body.en}
                  </p>
                </li>
              ))}
            </ul>
            <Button variant="link" className="w-fit px-0" onClick={openPage}>
              {t("whats_new_announcement_all", { count: entries.length })}
              <ArrowRight className="size-4" />
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
