import { Banner } from "@astryxdesign/core/Banner";
import { useEffect, useRef, useState } from "react";
import { useTranslations } from "use-intl";
import { LoadingState } from "@/components/composites/loading-state";
import { getSessionSnapshot, handleRefusal, SESSION_GENERATION_HEADER } from "@/lib/api/refusal";
import { safeNextPath } from "@/lib/auth/safe-next";
import { navigateTo } from "@/lib/navigate-to";
import { PublicPage } from "./public-page";

export function logoutTarget({ reason, next }: { reason?: string; next?: string }): string {
  const message = reason === "expired" || reason === "password_changed" ? reason : "logout";
  const search = new URLSearchParams({ message });
  if (message === "password_changed" && next && safeNextPath(next) === next)
    search.set("next", next);
  return `/login?${search}`;
}

async function signOut(): Promise<boolean> {
  const session = getSessionSnapshot();
  if (session.status === "stale" || session.status === "unbound") return false;
  const headers: Record<string, string> = {};
  const generation =
    session.status === "deactivated"
      ? session.generation
      : (session.generation ?? session.logoutGeneration);
  if (generation) {
    headers[SESSION_GENERATION_HEADER] = generation;
  }
  // Public identity operation: it must also work when no cookie is present.
  const response = await fetch("/api/v1/auth/session/logout/", {
    method: "POST",
    credentials: "same-origin",
    redirect: "error",
    headers
  });
  if (!response.ok) await handleRefusal(response, "/api/v1/auth/session/logout/");
  return response.ok;
}

/** Logout and organisation switch share one committed, full-document handoff. */
export function LogoutHandoff({
  target,
  accessibilityStatementUrl = null
}: {
  target: string;
  accessibilityStatementUrl?: string | null;
}) {
  const started = useRef(false);
  const [failed, setFailed] = useState(false);
  const t = useTranslations();
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void signOut()
      .then((ok) => {
        if (ok) navigateTo(target, { replace: true });
        else setFailed(true);
      })
      .catch(() => setFailed(true));
  }, [target]);

  return (
    <PublicPage title={t("logout")} accessibilityStatementUrl={accessibilityStatementUrl}>
      {failed ? (
        <>
          <Banner status="error" title={t("logout_failed")} />
          <a
            href="/logout"
            className="text-ax-text-accent inline-flex min-h-11 items-center justify-center underline underline-offset-4"
          >
            {t("try_again")}
          </a>
        </>
      ) : (
        <LoadingState rows={1} label={t("logout_pending")} />
      )}
    </PublicPage>
  );
}
