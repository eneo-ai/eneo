import { useEffect, useRef } from "react";
import { useTranslations } from "use-intl";
import { LoadingState } from "@/components/composites/loading-state";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError } from "@/lib/api/errors";
import { getSessionSnapshot } from "@/lib/api/refusal";
import {
  loginPathToResume,
  MODULE_LOGIN_PATH,
  moduleLoginFailurePath,
  parseModuleLoginRequest,
  redirectTargetFromBody,
  ticketOutcome
} from "@/lib/auth/module-login";
import { navigateTo } from "@/lib/navigate-to";
import { PublicPage } from "./public-page";

async function handoff(search: string): Promise<void> {
  const request = parseModuleLoginRequest(new URLSearchParams(search));
  let target = moduleLoginFailurePath("invalid_request");
  if (request) {
    let status = 500;
    let body: unknown;
    try {
      const result = await browserApi.POST("/api/v1/module-auth/tickets/", {
        body: {
          module_key: request.moduleKey,
          redirect_uri: request.redirectUri,
          state: request.state
        },
        cache: "no-store",
        redirect: "error"
      });
      status = result.response.status;
      body = result.data;
    } catch (error) {
      // The shared owner has already blocked a changed identity or a restricted
      // session. Do not replace its recovery destination with a module failure.
      if (getSessionSnapshot().status === "stale") return;
      if (error instanceof EneoApiError) status = error.status;
    }
    const outcome = ticketOutcome(status);
    target =
      outcome.kind === "login"
        ? loginPathToResume(MODULE_LOGIN_PATH + search)
        : outcome.kind === "failure"
          ? moduleLoginFailurePath(outcome.reason)
          : (redirectTargetFromBody(body) ?? moduleLoginFailurePath("service_unavailable"));
  }
  navigateTo(target, { replace: true });
}

export function ModuleLoginPage({
  search,
  accessibilityStatementUrl
}: {
  search: string;
  accessibilityStatementUrl: string | null;
}) {
  const t = useTranslations();
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void handoff(search);
  }, [search]);
  return (
    <PublicPage title={t("redirecting")} accessibilityStatementUrl={accessibilityStatementUrl}>
      <LoadingState rows={1} />
    </PublicPage>
  );
}
