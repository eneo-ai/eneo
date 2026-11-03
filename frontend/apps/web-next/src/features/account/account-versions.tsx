import { useTranslations } from "use-intl";
import { useAppContext } from "@/components/providers/app-context";

/** The same compiled frontend identity in the account card and phone footer. */
export function AccountVersions() {
  const t = useTranslations();
  const { versions } = useAppContext();
  return (
    <>
      {t("version_frontend")} {versions.frontend}
      {versions.frontendRevision ? (
        <>
          {" "}
          (<code className="break-all">{versions.frontendRevision}</code>)
        </>
      ) : null}
      {` · ${t("version_backend")} ${versions.backend || "–"}`}
    </>
  );
}
