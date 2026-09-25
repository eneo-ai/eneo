"use client";

import type { Locale, ReleaseEntry } from "@eneo/whats-new";
import { useLocale, useTranslations } from "next-intl";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { runTour, type TourOutcome } from "./tour";

interface TourContextValue {
  running: boolean;
  start: (entries: ReleaseEntry[], version: string) => Promise<TourOutcome>;
  stop: () => void;
}

const TourContext = createContext<TourContextValue | null>(null);

export function TourProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const locale = useLocale() as Locale;
  const t = useTranslations();
  const [running, setRunning] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const expectedPath = useRef<string | null>(null);

  const stop = useCallback(() => controller.current?.abort(), []);
  useEffect(() => stop, [stop]);
  useEffect(() => {
    if (!controller.current) return;
    if (expectedPath.current === pathname) {
      expectedPath.current = null;
      return;
    }
    if (expectedPath.current === null) stop();
  }, [pathname, stop]);

  const start = useCallback(
    async (entries: ReleaseEntry[], version: string): Promise<TourOutcome> => {
      stop();
      const session = new AbortController();
      controller.current = session;
      setRunning(true);
      const escape = (event: KeyboardEvent) => {
        if (event.key === "Escape") session.abort();
      };
      window.addEventListener("keydown", escape);
      try {
        return await runTour(
          entries,
          locale,
          {
            done: t("whats_new_spotlight_done"),
            next: t("whats_new_tour_next"),
            previous: t("whats_new_tour_previous"),
            progress: t("whats_new_tour_progress", { current: "{current}", total: "{total}" }),
            version: t("whats_new_tour_version", { version })
          },
          (href) => {
            expectedPath.current = new URL(href, window.location.href).pathname;
            router.push(href);
          },
          session.signal
        );
      } finally {
        window.removeEventListener("keydown", escape);
        if (controller.current === session) {
          controller.current = null;
          expectedPath.current = null;
          setRunning(false);
        }
      }
    },
    [locale, router, stop, t]
  );

  return <TourContext.Provider value={{ running, start, stop }}>{children}</TourContext.Provider>;
}

export function useTour(): TourContextValue {
  const context = useContext(TourContext);
  if (!context) throw new Error("useTour must be used inside the app layout");
  return context;
}
