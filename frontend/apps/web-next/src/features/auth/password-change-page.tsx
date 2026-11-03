import { Button } from "@astryxdesign/core/Button";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useTranslations } from "use-intl";
import { LoadingState } from "@/components/composites/loading-state";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { ChangePasswordForm } from "@/features/account/change-password";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError } from "@/lib/api/errors";
import { getSessionSnapshot } from "@/lib/api/refusal";
import { sessionQueries } from "@/lib/api/session";
import { loginPathToResume } from "@/lib/auth/module-login";
import { passwordChangeUrl, passwordChangedLogoutUrl } from "@/lib/auth/password-change-path";
import { safeNextPath } from "@/lib/auth/safe-next";
import { navigateTo } from "@/lib/navigate-to";
import { DocumentLink } from "./document-link";
import { passwordCapability } from "./password-policy";
import { PublicPage } from "./public-page";

export function PasswordChangePage({
  next,
  accessibilityStatementUrl
}: {
  next?: string;
  accessibilityStatementUrl: string | null;
}) {
  const t = useTranslations();
  const session = getSessionSnapshot();
  const bound = session.status === "bound" && session.generation !== null;
  const me = useQuery({ ...sessionQueries(browserApi).me, enabled: bound, retry: false });
  const continued = useRef(false);
  const destination = !bound
    ? loginPathToResume(passwordChangeUrl(next))
    : me.error instanceof EneoApiError && me.error.status === 401
      ? "/logout?reason=expired"
      : me.data && !me.data.password_status?.change_required
        ? safeNextPath(next)
        : null;
  useEffect(() => {
    if (destination && !continued.current) {
      continued.current = true;
      navigateTo(destination, { replace: true });
    }
  }, [destination]);
  const capability = passwordCapability(me.data?.password_change);
  const expired = me.data?.password_status?.reason === "expired";
  return (
    <PublicPage
      title={t("password_change_required_title")}
      description={t(
        expired ? "password_change_required_expired" : "password_change_required_admin_set"
      )}
      width="md"
      accessibilityStatementUrl={accessibilityStatementUrl}
      footer={<Button as={DocumentLink} href="/logout" label={t("logout")} />}
    >
      {destination ? (
        <LoadingState rows={1} />
      ) : (
        <QueryStateBoundary query={me} rows={1}>
          {(user) =>
            capability.source === "eneo" ? (
              <ChangePasswordForm
                policy={capability.policy}
                email={user.email}
                currentPasswordHint={t(
                  expired
                    ? "password_change_required_expired_current_hint"
                    : "password_change_required_current_hint"
                )}
                afterChangeHref={passwordChangedLogoutUrl(next)}
              />
            ) : (
              <p className="text-ax-text-secondary text-sm">{t("password_change_not_available")}</p>
            )
          }
        </QueryStateBoundary>
      )}
    </PublicPage>
  );
}
