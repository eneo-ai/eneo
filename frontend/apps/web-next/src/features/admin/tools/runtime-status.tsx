"use client";

import { useTranslations } from "next-intl";
import { runtimeMessageKeys, type RuntimeStatus } from "./bundled";

/** The state of the tool runtime shipped with Eneo, as the backend last saw it. */
export function RuntimeStatusCard({ status }: { status: RuntimeStatus | null | undefined }) {
  const t = useTranslations();
  if (!status) return null;
  return (
    <section
      aria-labelledby="runtime-status-title"
      className="border-ax-border rounded-ax-container border p-5"
    >
      <h2 id="runtime-status-title" className="font-semibold">
        {t("tools_runtime_title")}
      </h2>
      <div className="text-ax-text-secondary mt-2 flex flex-col gap-2 text-sm">
        {runtimeMessageKeys(status).map((key) => (
          <p key={key}>{t(key)}</p>
        ))}
        {status.version && (
          <p>
            {t("tools_runtime_versions", {
              backend: status.expected_version,
              runtime: status.version
            })}
          </p>
        )}
      </div>
    </section>
  );
}
