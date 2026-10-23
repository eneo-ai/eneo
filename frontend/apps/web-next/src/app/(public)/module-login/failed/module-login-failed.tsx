import { Button } from "@astryxdesign/core/Button";
import { useTranslations } from "next-intl";
import type { ModuleLoginFailureReason } from "@/lib/auth/module-login";
import { DEFAULT_LANDING } from "@/lib/auth/safe-next";
import { PublicPage } from "../../public-page";

const DESCRIPTION_KEY: Record<ModuleLoginFailureReason, string> = {
  invalid_request: "module_login_invalid_request",
  module_unavailable: "module_login_unavailable",
  service_unavailable: "module_login_service_unavailable"
};

/**
 * What went wrong with a module's login hand-off and what to do about it,
 * with the way back into Eneo. Rendered by the failed page with the reason
 * `/module-login` named.
 */
export function ModuleLoginFailed({ reason }: { reason: ModuleLoginFailureReason }) {
  const t = useTranslations();

  return (
    <PublicPage
      title={t("module_login_failed")}
      footer={
        <Button href={DEFAULT_LANDING} label={t("module_login_back_to_eneo")} variant="primary" />
      }
    >
      <p className="text-ax-text-secondary text-sm">{t(DESCRIPTION_KEY[reason])}</p>
    </PublicPage>
  );
}
