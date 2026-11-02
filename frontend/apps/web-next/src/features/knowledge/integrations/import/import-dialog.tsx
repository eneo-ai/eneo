import { RadioList, RadioListItem } from "@astryxdesign/core/RadioList";
import { Button as AstryxButton } from "@astryxdesign/core/Button";
import { useQuery } from "@tanstack/react-query";
import Link from "@/lib/link";
import { useTranslations } from "use-intl";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { browserApi } from "@/lib/api/browser";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { useAppContext } from "@/components/providers/app-context";
import { useSpace } from "@/features/spaces/use-space";
import { availableIntegrationsQueryOptions, type UserIntegration } from "../queries";
import { VENDOR, VendorIcon } from "../vendor";
import { integrationSetupAction } from "../setup-action";
import { ConfluenceImportDialog } from "./confluence-import";
import { SharePointImportDialog } from "./sharepoint-import";

/**
 * Knowledge-import integrations for this space. Matches the Svelte knowledge
 * layout: SharePoint only (Confluence import is disabled there too), and
 * personal spaces offer user-OAuth integrations while shared/org spaces offer
 * admin-configured tenant apps.
 */
export function useImportableIntegrations() {
  const { space } = useSpace();
  const query = useQuery(availableIntegrationsQueryOptions(browserApi, space.id));

  const importable = (query.data ?? []).filter(
    (entry) => entry.integration_type === "sharepoint" || entry.integration_type === "confluence"
  );
  const integrations = space.personal
    ? importable.filter((entry) => entry.auth_type === "user_oauth" || !entry.connected)
    : importable.filter((entry) => entry.connected && entry.auth_type === "tenant_app");

  return { integrations, isPending: query.isPending, query };
}

/**
 * One integration to import from, as a radio: the choice is exclusive. One
 * that is not connected cannot be chosen, and says where to connect it.
 */
function integrationOption(integration: UserIntegration, t: ReturnType<typeof useTranslations>) {
  const vendor = VENDOR[integration.integration_type];
  return (
    <RadioListItem
      key={integration.tenant_integration_id}
      value={integration.tenant_integration_id}
      isDisabled={!integration.connected}
      startContent={<VendorIcon type={integration.integration_type} size={32} />}
      label={
        <span className="flex items-center gap-2">
          <span className="font-semibold">{integration.name}</span>
          <Badge variant={integration.auth_type === "tenant_app" ? "default" : "secondary"}>
            {integration.auth_type === "tenant_app" ? t("organization") : t("personal")}
          </Badge>
        </span>
      }
      description={
        <>
          {t(vendor.importHint)}
          {!integration.connected && (
            <span className="block">
              {t("enable_integration_in_account_settings", { name: integration.name })}
            </span>
          )}
        </>
      }
    />
  );
}

/** Step 1: pick a connected integration; step 2: the vendor's import dialog. */
export function ImportKnowledgeDialog({
  open,
  onOpenChange
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const { space } = useSpace();
  const { integrations, query } = useImportableIntegrations();
  const { can } = useAppContext();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [step, setStep] = useState<"select" | "import">("select");

  const firstConnected = integrations.find((entry) => entry.connected) ?? null;
  const selected =
    integrations.find((entry) => entry.tenant_integration_id === selectedId) ?? firstConnected;

  const setup = integrationSetupAction({
    importableCount: 0,
    personal: space.personal,
    organization: space.organization,
    isAdmin: can("admin")
  });
  const settingsHref = setup.kind === "link" ? setup.href : null;

  return (
    <>
      <Dialog open={open && step === "select"} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{t("import_knowledge")}</DialogTitle>
            <DialogDescription>
              {space.personal
                ? t("import_knowledge_from_third_party")
                : t("import_knowledge_from_org_integrations")}{" "}
              {settingsHref && (
                <Link href={settingsHref} className="underline">
                  {t(space.personal ? "personal_account" : "admin_settings")}
                </Link>
              )}
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <QueryStateBoundary query={query} rows={2} loadingLabel={t("loading_integrations")}>
              {() =>
                integrations.length === 0 ? (
                  <div className="flex flex-col items-center gap-3 py-8 text-center text-sm">
                    <p className="text-ax-text-secondary">{t("no_integrations_available")}</p>
                    {setup.kind === "link" ? (
                      <AstryxButton label={t("configure_integrations")} href={setup.href} />
                    ) : setup.kind === "message" ? (
                      <p>{t(setup.messageKey)}</p>
                    ) : null}
                  </div>
                ) : (
                  <RadioList
                    label={t("integrations")}
                    isLabelHidden
                    value={selected?.tenant_integration_id ?? ""}
                    onChange={setSelectedId}
                  >
                    {integrations.map((integration) => integrationOption(integration, t))}
                  </RadioList>
                )
              }
            </QueryStateBoundary>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              {t("cancel")}
            </Button>
            <Button disabled={!selected?.connected} onClick={() => setStep("import")}>
              {t("continue")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {selected &&
        (selected.integration_type === "confluence" ? (
          <ConfluenceImportDialog
            open={open && step === "import"}
            onOpenChange={(next) => {
              if (!next) setStep("select");
              onOpenChange(next);
            }}
            onBack={() => setStep("select")}
            integration={selected}
          />
        ) : (
          <SharePointImportDialog
            open={open && step === "import"}
            onOpenChange={(next) => {
              if (!next) setStep("select");
              onOpenChange(next);
            }}
            onBack={() => setStep("select")}
            integration={selected}
          />
        ))}
    </>
  );
}
