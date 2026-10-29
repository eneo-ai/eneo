import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { useTranslations } from "use-intl";
import { useEffect, useRef, useSyncExternalStore, type ReactNode } from "react";
import {
  checkBrowserSession,
  getSessionSnapshot,
  listenForSessionResume,
  reloadSession,
  subscribeSession
} from "@/lib/api/refusal";

/** Vite's transport owns the state; this boundary only presents it. */
export function BrowserSessionBoundary({ children }: { children: ReactNode }) {
  const session = useSyncExternalStore(subscribeSession, getSessionSnapshot, getSessionSnapshot);
  const heading = useRef<HTMLHeadingElement>(null);
  const t = useTranslations();
  useEffect(listenForSessionResume, []);
  useEffect(() => {
    if (session.status === "stale") heading.current?.focus();
  }, [session.status]);

  if (session.status === "stale") {
    return (
      <main className="flex min-h-dvh flex-col items-center justify-center gap-4 p-8 text-center">
        <h1 ref={heading} tabIndex={-1} className="text-ax-text text-2xl font-semibold">
          {t("session_changed_title")}
        </h1>
        <p className="text-ax-text-secondary max-w-prose text-sm">
          {t("session_changed_description")}
        </p>
        <Button label={t("session_reload")} variant="primary" onClick={reloadSession} />
      </main>
    );
  }

  return (
    <>
      {session.status === "bound" && session.checkError !== undefined && (
        <Banner
          status="error"
          container="section"
          title={t("session_check_failed")}
          description={t("session_check_retry_description")}
          endContent={
            <Button
              label={t("try_again")}
              isInterruptible
              clickAction={() => checkBrowserSession().catch(() => {})}
            />
          }
        />
      )}
      {children}
    </>
  );
}
