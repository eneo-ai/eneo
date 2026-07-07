"use client";

import { ExternalLink, Info } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

export function CrawlLimitationsBanner({
  integrationRequestFormUrl
}: {
  integrationRequestFormUrl: string;
}) {
  const t = useTranslations();

  return (
    <Alert>
      <Info className="size-4" />
      <AlertTitle>{t("limitations")}</AlertTitle>
      <AlertDescription>
        <p>{t("crawl_limitations_description")}</p>
        <a
          href={integrationRequestFormUrl}
          target="_blank"
          rel="noreferrer"
          className="text-foreground inline-flex items-center gap-1 underline underline-offset-2"
        >
          {t("request_integrations_feedback")}
          <ExternalLink className="size-3.5" />
        </a>
      </AlertDescription>
    </Alert>
  );
}

export function IntegrationsBetaNotice({
  integrationRequestFormUrl
}: {
  integrationRequestFormUrl: string;
}) {
  const t = useTranslations();
  const [visible, setVisible] = useState(true);

  if (!visible) return null;

  return (
    <Alert>
      <Info className="size-4" />
      <AlertTitle>{t("beta_version")}</AlertTitle>
      <AlertDescription className="pr-24">
        <p>
          {t("integrations_beta_notice")}{" "}
          <a
            href={integrationRequestFormUrl}
            target="_blank"
            rel="noreferrer"
            className="text-foreground inline-flex items-center gap-1 underline underline-offset-2"
          >
            {t("request_integrations_feedback")}
            <ExternalLink className="size-3.5" />
          </a>
        </p>
      </AlertDescription>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="absolute top-3 right-3"
        onClick={() => setVisible(false)}
      >
        {t("dismiss")}
      </Button>
    </Alert>
  );
}
