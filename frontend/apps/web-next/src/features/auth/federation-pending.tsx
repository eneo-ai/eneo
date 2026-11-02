import { Button } from "@astryxdesign/core/Button";
import { useEffect, useState } from "react";
import { useTranslations } from "use-intl";
import { Banner } from "@astryxdesign/core/Banner";
import { LoadingState } from "@/components/composites/loading-state";
import { useAnnounceChange } from "@/lib/hooks/use-announce-change";
import { DocumentLink } from "./document-link";

/** A stalled document handoff remains recoverable without retrying authentication automatically. */
export function FederationPending({ href }: { href: string }) {
  const t = useTranslations();
  const [slow, setSlow] = useState(false);
  useAnnounceChange(slow ? t("connection_slow_warning") : null, slow);
  useEffect(() => {
    const timer = window.setTimeout(() => setSlow(true), 10_000);
    return () => window.clearTimeout(timer);
  }, []);
  return (
    <>
      <LoadingState rows={1} label={t("redirecting_to_authentication")} />
      {slow ? (
        <>
          <Banner status="warning" title={t("connection_slow_warning")} />
          <Button label={t("retry")} href={href} as={DocumentLink} />
        </>
      ) : null}
    </>
  );
}
