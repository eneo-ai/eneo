import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { useTranslations } from "use-intl";
import { safeNextPath } from "@/lib/auth/safe-next";
import { DocumentLink } from "./document-link";
import { CorrelationReference } from "./login-diagnostics-alert";
import { mfaSignInHref } from "./sso-entry";

/** How a sign-in for multi-factor authentication can end without one. */
export type MfaSignInEnd = "mfa_not_met" | "mfa_not_configured";

export function mfaSignInEnd(detailCode: string | undefined): MfaSignInEnd | null {
  return detailCode === "mfa_not_met" || detailCode === "mfa_not_configured" ? detailCode : null;
}

/**
 * Where a sign-in for MFA ends when it gave none. The person still has the
 * session they came with, so nothing here starts another sign-in or sends
 * them on by itself: both ways out are theirs to press.
 */
export function MfaSignInEnded({
  reason,
  next,
  correlation
}: {
  reason: MfaSignInEnd;
  next?: string;
  correlation?: string;
}) {
  const t = useTranslations();
  const notMet = reason === "mfa_not_met";
  return (
    <>
      <Banner
        status="warning"
        title={t(notMet ? "mfa_sign_in_not_met_title" : "mfa_sign_in_not_configured_title")}
        description={t(
          notMet ? "mfa_sign_in_not_met_description" : "mfa_sign_in_not_configured_description"
        )}
        collapsible={false}
      >
        {correlation ? <CorrelationReference id={correlation} /> : null}
      </Banner>
      {notMet ? (
        <Button
          label={t("mfa_sign_in_retry")}
          href={mfaSignInHref(next ?? "/")}
          as={DocumentLink}
          variant="primary"
        />
      ) : null}
      <Button
        label={t("mfa_sign_in_back")}
        href={safeNextPath(next)}
        as={DocumentLink}
        variant={notMet ? "secondary" : "primary"}
      />
    </>
  );
}
