import { Button } from "@astryxdesign/core/Button";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, type Ref } from "react";
import { useTranslations } from "use-intl";
import { LoadingState } from "@/components/composites/loading-state";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError } from "@/lib/api/errors";
import { getSessionSnapshot } from "@/lib/api/refusal";
import { sessionQueries } from "@/lib/api/session";
import { DEFAULT_LANDING } from "@/lib/auth/safe-next";
import { navigateTo } from "@/lib/navigate-to";
import { DocumentLink } from "./document-link";
import { PublicPage } from "./public-page";

export function DeactivatedNotice({
  accessibilityStatementUrl,
  headingRef
}: {
  accessibilityStatementUrl: string | null;
  headingRef?: Ref<HTMLHeadingElement>;
}) {
  const t = useTranslations();
  return (
    <PublicPage
      title={t("organisation_deactivated")}
      width="md"
      accessibilityStatementUrl={accessibilityStatementUrl}
      headingRef={headingRef}
      footer={
        <>
          <Button as={DocumentLink} href="/logout" label={t("logout")} />
          <Button as={DocumentLink} href="/deactivated" label={t("retry")} variant="primary" />
        </>
      }
    >
      <p className="text-ax-text-secondary text-sm">{t("access_disabled")}</p>
    </PublicPage>
  );
}

export function DeactivatedPage({
  accessibilityStatementUrl
}: {
  accessibilityStatementUrl: string | null;
}) {
  const t = useTranslations();
  const session = getSessionSnapshot();
  const bound = session.status === "bound" && session.generation !== null;
  const me = useQuery({ ...sessionQueries(browserApi).me, enabled: bound, retry: false });
  const continued = useRef(false);
  const signedOut = !bound || (me.error instanceof EneoApiError && me.error.status === 401);
  useEffect(() => {
    if (!continued.current && (signedOut || me.data)) {
      continued.current = true;
      navigateTo(signedOut ? "/login" : DEFAULT_LANDING, { replace: true });
    }
  }, [signedOut, me.data]);
  return (
    <PublicPage
      title={t("organisation")}
      accessibilityStatementUrl={accessibilityStatementUrl}
      footer={<Button as={DocumentLink} href="/logout" label={t("logout")} />}
    >
      <QueryStateBoundary query={me} rows={1}>
        {() => <LoadingState rows={1} />}
      </QueryStateBoundary>
    </PublicPage>
  );
}
