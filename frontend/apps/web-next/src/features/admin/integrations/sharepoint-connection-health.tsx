"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { VisuallyHidden } from "@astryxdesign/core/VisuallyHidden";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Circle, TriangleAlert, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useRef, useState, type ReactNode } from "react";
import { useClientTimeText } from "@/components/composites/client-time";
import { browserApi } from "@/lib/api/browser";
import { getErrorMessage, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { useFocusRescue } from "@/lib/focus-rescue";
import { cn } from "@/lib/utils";
import {
  SHAREPOINT_APP_KEY,
  type SharePointApp,
  sharepointSubscriptionsQueryOptions
} from "./integrations";
import { followServiceAccountSignIn, toastSignInError } from "./service-account-sign-in";
import { SharePointSubscriptions, useRenewExpiredSubscriptions } from "./sharepoint-subscriptions";

export type HealthState = "ok" | "warning" | "error" | "unknown";

/** The most severe of the checks, for a summary badge. */
export function worstHealth(states: readonly HealthState[]): HealthState {
  for (const level of ["error", "warning", "unknown"] as const) {
    if (states.includes(level)) return level;
  }
  return "ok";
}

type MicrosoftAuthGuidance = "invalid_client" | "interaction_required" | "invalid_grant";

// AADSTS50076 arrives inside an invalid_grant envelope, so the interactive
// sign-in case must win over the generic grant failure. AADSTS9002313 is what
// a refresh with a stale or garbled refresh token returns.
const GUIDANCE_PATTERNS: ReadonlyArray<[MicrosoftAuthGuidance, RegExp]> = [
  ["invalid_client", /AADSTS7000215|invalid_client/i],
  ["interaction_required", /AADSTS50076|interaction_required/i],
  ["invalid_grant", /invalid_grant|AADSTS9002313/i]
];

/** Which short guidance fits a raw Microsoft identity error, if any. */
export function classifyMicrosoftAuthError(
  message: string | null | undefined
): MicrosoftAuthGuidance | null {
  if (!message) return null;
  return GUIDANCE_PATTERNS.find(([, pattern]) => pattern.test(message))?.[0] ?? null;
}

const STATE_STYLES: Record<HealthState, string> = {
  ok: "bg-ax-success-muted text-ax-success",
  warning: "bg-ax-warning-muted text-ax-warning",
  error: "bg-ax-error-muted text-ax-error",
  unknown: "bg-ax-muted text-ax-text-secondary"
};

const STATE_ICONS: Record<HealthState, typeof Check> = {
  ok: Check,
  warning: TriangleAlert,
  error: X,
  unknown: Circle
};

const BADGE_VARIANTS = {
  ok: "success",
  warning: "warning",
  error: "error",
  unknown: "neutral"
} as const satisfies Record<HealthState, string>;

const STATE_LABEL_KEYS: Record<HealthState, string> = {
  ok: "sharepoint_health_state_ok",
  warning: "sharepoint_health_state_warning",
  error: "sharepoint_health_state_error",
  unknown: "sharepoint_health_state_unknown"
};

/** One check: its state as an icon (named for screen readers), what it is, and its actions. */
function HealthCheck({
  state,
  title,
  children,
  actions,
  extra
}: {
  state: HealthState;
  title: string;
  children: ReactNode;
  actions?: ReactNode;
  /** Full-width content under the check, such as a panel its action opens. */
  extra?: ReactNode;
}) {
  const t = useTranslations();
  const Icon = STATE_ICONS[state];
  return (
    <li className="border-ax-border flex flex-wrap items-start gap-3 border-b px-4 py-4 last:border-b-0">
      <span
        aria-hidden="true"
        className={cn(
          "flex size-7 shrink-0 items-center justify-center rounded-full",
          STATE_STYLES[state]
        )}
      >
        <Icon className={state === "unknown" ? "size-3" : "size-3.5"} />
      </span>
      <div className="flex min-w-0 flex-[1_1_18rem] flex-col gap-1">
        <p className="font-medium">
          <VisuallyHidden>{t(STATE_LABEL_KEYS[state])}: </VisuallyHidden>
          {title}
        </p>
        {children}
      </div>
      {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
      {extra ? <div className="min-w-0 basis-full">{extra}</div> : null}
    </li>
  );
}

function signInHealth(config: SharePointApp): HealthState {
  if (config.auth_status === "ok") return "ok";
  return config.auth_status === "error" ? "error" : "unknown";
}

function SignInCheck({ config, onEdit }: { config: SharePointApp; onEdit: () => void }) {
  const t = useTranslations();
  const state = signInHealth(config);
  const guidance = classifyMicrosoftAuthError(config.last_auth_error);
  const errorAt = useClientTimeText(config.last_auth_error_at, "date_time");
  const successAt = useClientTimeText(config.last_auth_success_at, "date_time");

  const reauth = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/admin/sharepoint/service-account/auth/reauth", {
          body: { redirect_uri: window.location.origin + "/integrations/callback/token/" }
        })
      ),
    onSuccess: (start) => followServiceAccountSignIn(start, t),
    onError: (error) => toastSignInError(error, t)
  });
  // Stays busy after success: the browser is on its way to Microsoft.
  const redirecting = reauth.isPending || reauth.isSuccess;

  const actions =
    state !== "error" ? null : config.auth_method === "service_account" ? (
      <Button
        label={redirecting ? t("redirecting") : t("sharepoint_reauth_with_microsoft")}
        variant="primary"
        size="sm"
        isLoading={redirecting}
        isInterruptible
        onClick={() => {
          if (!redirecting) reauth.mutate();
        }}
      />
    ) : (
      <Button label={t("update_configuration")} variant="primary" size="sm" onClick={onEdit} />
    );

  return (
    <HealthCheck state={state} title={t("sharepoint_health_sign_in_title")} actions={actions}>
      {state === "error" ? (
        <>
          <p className="text-sm">
            {guidance
              ? t(`sharepoint_auth_guidance_${guidance}`)
              : errorAt
                ? t("sharepoint_health_sign_in_error", { time: errorAt })
                : t("sharepoint_health_sign_in_refused")}
          </p>
          <p className="text-ax-text-secondary text-sm">{t("sharepoint_health_sign_in_impact")}</p>
          {config.last_auth_error ? (
            <details className="text-ax-text-secondary text-xs">
              <summary className="focus-visible:outline-ring rounded-ax-inner w-fit cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2">
                {t("sharepoint_auth_error_details")}
              </summary>
              <p className="mt-1 font-mono break-words">{config.last_auth_error}</p>
            </details>
          ) : null}
        </>
      ) : (
        <p className="text-ax-text-secondary text-sm">
          {state === "ok" && successAt
            ? t("sharepoint_auth_last_success", { time: successAt })
            : t("sharepoint_health_sign_in_unknown")}
        </p>
      )}
    </HealthCheck>
  );
}

/** The change notifications (Graph webhooks) that keep imported folders current. */
function useWatchHealth() {
  const query = useQuery(sharepointSubscriptionsQueryOptions(browserApi));
  const subscriptions = query.data;
  const expired = subscriptions?.filter((s) => s.is_expired).length ?? 0;
  const failing =
    subscriptions?.filter((s) => !s.is_expired && s.consecutive_renewal_failures > 0).length ?? 0;
  const total = subscriptions?.length ?? 0;
  const state: HealthState = total === 0 ? "unknown" : expired + failing > 0 ? "warning" : "ok";
  return { query, total, expired, failing, active: total - expired - failing, state };
}

function WatchCheck({ watch }: { watch: ReturnType<typeof useWatchHealth> }) {
  const t = useTranslations();
  const renewExpired = useRenewExpiredSubscriptions();
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const toggleRef = useRef<HTMLButtonElement>(null);
  const rescue = useFocusRescue();
  const { query, total, expired, failing, active } = watch;

  const description = query.isPending
    ? t("loading")
    : query.isError && !query.data
      ? t("sharepoint_subscriptions_load_error")
      : total === 0
        ? t("sharepoint_health_watch_none")
        : failing === 0 && expired > 0
          ? t("sharepoint_health_watch_issues_expired", { active, total, expired })
          : expired === 0 && failing > 0
            ? t("sharepoint_health_watch_issues_failing", { active, total, failing })
            : expired + failing > 0
              ? t("sharepoint_health_watch_issues", { active, total, expired, failing })
              : active === 1
                ? t("sharepoint_health_watch_ok_one")
                : t("sharepoint_health_watch_ok_other", { count: active });

  return (
    <HealthCheck
      state={watch.state}
      title={t("sharepoint_health_watch_title")}
      actions={
        <>
          {expired > 0 ? (
            <Button
              label={t("sharepoint_health_watch_renew")}
              size="sm"
              isLoading={renewExpired.isPending}
              isInterruptible
              onClick={() => {
                if (renewExpired.isPending) return;
                // Once nothing has expired the button goes; focus moves to its neighbour.
                renewExpired.mutate(undefined, { onSuccess: () => rescue(toggleRef.current) });
              }}
            />
          ) : null}
          <Button
            ref={toggleRef}
            label={open ? t("sharepoint_health_watch_hide") : t("sharepoint_health_watch_show")}
            variant="ghost"
            size="sm"
            aria-expanded={open}
            aria-controls={open ? panelId : undefined}
            onClick={() => setOpen((value) => !value)}
          />
        </>
      }
      extra={
        open ? (
          <div
            id={panelId}
            className="border-ax-border rounded-ax-container mt-2 border p-4 sm:p-6"
          >
            <SharePointSubscriptions />
          </div>
        ) : null
      }
    >
      <p className="text-ax-text-secondary text-sm">{description}</p>
    </HealthCheck>
  );
}

function ConnectionTestCheck() {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const announce = useAnnounce();
  const [result, setResult] = useState<Schema<"TenantAppTestResult"> | null>(null);

  const runTest = useMutation({
    mutationFn: () => unwrap(browserApi.POST("/api/v1/admin/sharepoint/app/test")),
    onMutate: () => setResult(null),
    onSuccess: (outcome) => {
      setResult(outcome);
      announce(
        outcome.success
          ? t("sharepoint_health_test_ok")
          : (outcome.error_message ?? t("sharepoint_health_state_error"))
      );
    },
    onError: (error) => {
      const message = getErrorMessage(error, t);
      setResult({ success: false, error_message: message });
      announce(message);
    },
    // The backend records the outcome as the app's credential health.
    onSettled: () => queryClient.invalidateQueries({ queryKey: SHAREPOINT_APP_KEY })
  });

  const state: HealthState = result === null ? "unknown" : result.success ? "ok" : "error";

  return (
    <HealthCheck
      state={state}
      title={t("sharepoint_health_test_title")}
      actions={
        <Button
          label={t("sharepoint_health_test_run")}
          size="sm"
          isLoading={runTest.isPending}
          isInterruptible
          onClick={() => {
            if (!runTest.isPending) runTest.mutate();
          }}
        />
      }
    >
      <p className="text-ax-text-secondary text-sm break-words">
        {runTest.isPending
          ? t("sharepoint_health_test_running")
          : result?.success
            ? t("sharepoint_health_test_ok")
            : result
              ? (result.error_message ?? t("sharepoint_health_state_error"))
              : t("sharepoint_health_test_description")}
      </p>
    </HealthCheck>
  );
}

/**
 * The SharePoint connection as a checklist: the app registration, the
 * Microsoft sign-in, the change notifications and an on-demand connection
 * test, each with the action that fixes it. The badge sums up the sign-in and
 * the notifications; the test only says something once it has run.
 */
export function SharePointConnectionHealth({
  config,
  onEdit
}: {
  config: SharePointApp;
  /** Opens the app configuration dialog. */
  onEdit: () => void;
}) {
  const t = useTranslations();
  const headingId = useId();
  const watch = useWatchHealth();
  const overall = worstHealth([signInHealth(config), watch.state]);

  return (
    <section
      aria-labelledby={headingId}
      className="border-ax-border bg-ax-card rounded-ax-container border"
    >
      <div className="border-ax-border flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3">
        <h3 id={headingId} className="font-semibold">
          {t("sharepoint_health_heading")}
        </h3>
        <Badge
          variant={BADGE_VARIANTS[overall]}
          label={
            overall === "ok" ? t("sharepoint_health_overall_ok") : t(STATE_LABEL_KEYS[overall])
          }
        />
      </div>
      <ol className="flex flex-col">
        <HealthCheck
          state="ok"
          title={t("sharepoint_health_app_title")}
          actions={<Button label={t("sharepoint_health_edit")} size="sm" onClick={onEdit} />}
        >
          <p className="text-ax-text-secondary text-sm break-words">
            {t("sharepoint_health_app_description", {
              domain: config.tenant_domain,
              client: config.client_id.slice(-4)
            })}
          </p>
          {config.auth_method === "service_account" && config.service_account_email ? (
            <p className="text-ax-text-secondary text-sm break-words">
              {t("sharepoint_health_service_account", { email: config.service_account_email })}
            </p>
          ) : null}
        </HealthCheck>
        <SignInCheck config={config} onEdit={onEdit} />
        <WatchCheck watch={watch} />
        <ConnectionTestCheck />
      </ol>
    </section>
  );
}
