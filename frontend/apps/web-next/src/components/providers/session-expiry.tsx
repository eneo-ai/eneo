import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Layout, LayoutContent, LayoutFooter } from "@astryxdesign/core/Layout";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { useFormatter, useTranslations } from "use-intl";
import { DocumentLink } from "@/features/auth/document-link";
import { extendBrowserSession, getSessionSnapshot, resumeLoginPath } from "@/lib/api/refusal";
import { navigateTo } from "@/lib/navigate-to";

/** Two minutes, as the UK government patterns. */
const WARNING_LEAD_MS = 120_000;
/** WCAG 2.2.1 asks for at least 20 seconds to extend. */
const LEAST_LEAD_MS = 20_000;
/** A screen reader hears the time left here, not every second. */
const ANNOUNCE_AT_SECONDS = [60, 30, 10];
/** Longer delays overflow setTimeout; a 30-day session waits in steps. */
const LONGEST_TIMEOUT_MS = 2 ** 31 - 1;

/**
 * Warns before the browser session ends and offers to stay signed in
 * (ACCESSIBILITY.md rule 15). At the end it keeps the page and offers to sign
 * in again, back to the same place.
 */
export function SessionExpiryDialog({
  expiresAt,
  lifetime = Infinity
}: {
  expiresAt: number;
  /** How long the session was issued for (ms); unknown on an older server. */
  lifetime?: number;
}) {
  const t = useTranslations();
  const format = useFormatter();
  const announce = useAnnounce();
  const descriptionId = useId();
  const [now, setNow] = useState(() => Date.now());
  const [failed, setFailed] = useState(false);
  // What was put away: the warning or the ended notice of one expiry. Putting
  // the warning away still lets the ended notice open when the time runs out.
  const [dismissed, setDismissed] = useState<string>();
  const [limitedAt, setLimitedAt] = useState<number>();
  const announcedDown = useRef(Infinity);

  // A session shorter than four minutes is warned for half of it, so staying
  // signed in leaves time to work; never under 20 seconds while that remains.
  // A session reopened with less than the lead left warns at once.
  const lead = Math.max(LEAST_LEAD_MS, Math.min(WARNING_LEAD_MS, lifetime / 2));
  const left = expiresAt - now;
  const warning = left <= lead;
  const expired = left <= 0;
  const notice = `${expiresAt}:${expired ? "ended" : "warning"}`;
  const open = warning && dismissed !== notice;
  // The renewal reached the session's maximum age: staying signed in again changes nothing.
  const limited = !expired && limitedAt === expiresAt;
  const ending = expired || limited;
  const secondsLeft = Math.max(0, Math.ceil(left / 1000));

  // Every tick reads the clock again, so a throttled or sleeping tab is right
  // as soon as it runs.
  useEffect(() => {
    if (warning) return;
    const wait = Math.min(expiresAt - lead - Date.now(), LONGEST_TIMEOUT_MS);
    const timer = window.setTimeout(() => setNow(Date.now()), Math.max(0, wait));
    return () => window.clearTimeout(timer);
  }, [expiresAt, lead, warning, now]);
  useEffect(() => {
    if (!warning || expired) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [warning, expired]);

  useEffect(() => {
    if (!warning) {
      announcedDown.current = Infinity;
      return;
    }
    if (expired) {
      if (announcedDown.current > 0) announce(t("your_session_expired"));
      announcedDown.current = 0;
      return;
    }
    const due = ANNOUNCE_AT_SECONDS.filter(
      (mark) => secondsLeft <= mark && mark < announcedDown.current
    );
    if (due.length === 0) return;
    announcedDown.current = Math.min(...due);
    announce(t("session_expiring_announcement", { seconds: secondsLeft }));
  }, [announce, expired, warning, secondsLeft, t]);

  async function stay() {
    setFailed(false);
    try {
      await extendBrowserSession();
      const session = getSessionSnapshot();
      const end = session.status === "bound" ? session.expiresAt : undefined;
      // At the limit the server renews only up to it, so the session still
      // ends within the warning.
      if (end !== undefined && end - Date.now() <= lead) {
        setLimitedAt(end);
        announce(t("session_extend_limit_title"));
      } else {
        announce(t("session_extended"));
      }
    } catch {
      // A refused session has already left this page; anything else can retry.
      setFailed(true);
    }
  }

  // Astryx's layer stack can call a handler from an earlier render, so Esc
  // reads the latest state through a ref: once the session has ended or cannot
  // be renewed it only puts the notice away.
  const close = useRef(() => {});
  useLayoutEffect(() => {
    close.current = () => (ending ? setDismissed(notice) : void stay());
  });

  return (
    <Dialog
      isOpen={open}
      // Esc keeps the session, as the button does.
      onOpenChange={() => close.current()}
      purpose="form"
      width={440}
      aria-describedby={descriptionId}
    >
      <Layout
        height="auto"
        header={
          <DialogHeader
            title={
              expired
                ? t("your_session_expired")
                : limited
                  ? t("session_extend_limit_title")
                  : t("session_expiring_title")
            }
          />
        }
        content={
          <LayoutContent>
            <div className="flex flex-col gap-3">
              <p id={descriptionId} className="text-ax-text text-sm">
                {expired
                  ? t("session_expired_description")
                  : t(
                      limited ? "session_extend_limit_description" : "session_expiring_description",
                      {
                        clock: format.dateTime(new Date(expiresAt), { timeStyle: "short" })
                      }
                    )}
              </p>
              {!expired && (
                <p aria-hidden="true" className="text-ax-text-secondary text-sm tabular-nums">
                  {t("session_expiring_remaining", {
                    time: `${Math.floor(secondsLeft / 60)}:${String(secondsLeft % 60).padStart(2, "0")}`
                  })}
                </p>
              )}
              {failed && !expired && <Banner status="error" title={t("session_extend_failed")} />}
            </div>
          </LayoutContent>
        }
        footer={
          <LayoutFooter>
            <div className="flex flex-wrap justify-end gap-2">
              {!expired && <Button as={DocumentLink} href="/logout" label={t("logout")} />}
              {/* One control for every state, so focus stays on it when the time
                  runs out. At the maximum age a session that is still valid is
                  not signed in again (the login page would continue it): the
                  notice closes, and signing in comes once it has ended. */}
              <Button
                data-autofocus
                variant="primary"
                label={
                  expired ? t("login_again") : limited ? t("close") : t("session_stay_signed_in")
                }
                isInterruptible
                clickAction={
                  expired
                    ? () => navigateTo(resumeLoginPath())
                    : limited
                      ? () => setDismissed(notice)
                      : stay
                }
              />
            </div>
          </LayoutFooter>
        }
      />
    </Dialog>
  );
}
