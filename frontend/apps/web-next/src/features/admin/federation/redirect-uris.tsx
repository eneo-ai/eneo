"use client";

import { Button } from "@astryxdesign/core/Button";
import { Text } from "@astryxdesign/core/Text";
import { Copy } from "lucide-react";
import { useTranslations } from "use-intl";
import { useCopy } from "@/lib/hooks/use-copy";

/**
 * The callback URIs to register at the identity provider, as text (never
 * links), each with a copy button named by its URI.
 */
export function RedirectUris({ uris, unavailable }: { uris: string[]; unavailable: boolean }) {
  const t = useTranslations();
  const { copy } = useCopy();

  if (unavailable || uris.length === 0) {
    return <Text type="supporting">{t("federation_admin_redirects_unavailable")}</Text>;
  }
  return (
    <ul className="flex flex-col gap-2">
      {uris.map((uri) => (
        <li key={uri} className="flex flex-wrap items-center gap-2">
          <code className="min-w-0 text-sm break-all">{uri}</code>
          <Button
            size="sm"
            label={t("copy")}
            aria-label={t("federation_admin_copy_uri", { uri })}
            icon={<Copy aria-hidden="true" />}
            onClick={() => void copy(uri)}
          />
        </li>
      ))}
    </ul>
  );
}
