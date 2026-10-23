"use client";

import { Banner } from "@astryxdesign/core/Banner";
import { Link } from "@astryxdesign/core/Link";
import { useTranslations } from "next-intl";

/** Why a crawl can miss content, with a link to request an integration instead. */
export function CrawlLimitationsBanner({
  integrationRequestFormUrl
}: {
  integrationRequestFormUrl: string;
}) {
  const t = useTranslations();

  return (
    <Banner
      status="info"
      title={t("limitations")}
      description={
        <span className="flex flex-col items-start gap-1">
          <span>{t("crawl_limitations_description")}</span>
          <Link href={integrationRequestFormUrl} isExternalLink hasUnderline>
            {t("request_integrations_feedback")}
          </Link>
        </span>
      }
    />
  );
}

/** Dismissable beta notice above the integrations list. */
export function IntegrationsBetaNotice({
  integrationRequestFormUrl
}: {
  integrationRequestFormUrl: string;
}) {
  const t = useTranslations();

  return (
    <Banner
      status="info"
      title={t("beta_version")}
      isDismissable
      dismissLabel={t("dismiss")}
      description={
        <span>
          {t("integrations_beta_notice")}{" "}
          <Link href={integrationRequestFormUrl} isExternalLink hasUnderline>
            {t("request_integrations_feedback")}
          </Link>
        </span>
      }
    />
  );
}
