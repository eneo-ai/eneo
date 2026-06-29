"use client";

import { useQuery } from "@tanstack/react-query";
import Image from "next/image";
import Link from "next/link";
import { useTranslations } from "next-intl";
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
import { Spinner } from "@/components/ui/spinner";
import { browserApi } from "@/lib/api/browser";
import { useSpace } from "@/features/spaces/use-space";
import { availableIntegrationsQueryOptions, type UserIntegration } from "../queries";
import { VENDOR } from "../vendor";
import { ConfluenceImportDialog } from "./confluence-import";
import { SharePointImportDialog } from "./sharepoint-import";

/**
 * Knowledge-import integrations for this space. Matches the Svelte knowledge
 * layout: SharePoint only (Confluence import is disabled there too), and
 * personal spaces offer user-OAuth integrations while shared/org spaces offer
 * admin-configured tenant apps.
 */
export function useImportableIntegrations(): {
  integrations: UserIntegration[];
  isPending: boolean;
} {
  const { space } = useSpace();
  const { data, isPending } = useQuery(availableIntegrationsQueryOptions(browserApi, space.id));

  const importable = (data ?? []).filter(
    (entry) => entry.integration_type === "sharepoint" || entry.integration_type === "confluence"
  );
  const integrations = space.personal
    ? importable.filter((entry) => entry.auth_type === "user_oauth" || !entry.connected)
    : importable.filter((entry) => entry.connected && entry.auth_type === "tenant_app");

  return { integrations, isPending };
}

function IntegrationCard({
  integration,
  selected,
  onSelect
}: {
  integration: UserIntegration;
  selected: boolean;
  onSelect: () => void;
}) {
  const t = useTranslations();
  const vendor = VENDOR[integration.integration_type];
  const disabled = !integration.connected;

  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onSelect}
      title={
        disabled
          ? t("enable_integration_in_account_settings", { name: integration.name })
          : undefined
      }
      className={`flex items-center gap-4 rounded-lg border p-3 text-left transition-colors ${
        selected ? "border-primary bg-accent" : "hover:bg-muted/50"
      } ${disabled ? "cursor-not-allowed opacity-60" : ""}`}
    >
      <Image src={vendor.logo} alt="" width={32} height={32} className="shrink-0" />
      <div className="flex min-w-0 flex-col">
        <span className="flex items-center gap-2">
          <span className="font-semibold">{integration.name}</span>
          <Badge variant={integration.auth_type === "tenant_app" ? "default" : "secondary"}>
            {integration.auth_type === "tenant_app" ? t("organization") : t("personal")}
          </Badge>
        </span>
        <span className="text-muted-foreground line-clamp-2 text-sm">{t(vendor.importHint)}</span>
      </div>
    </button>
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
  const { integrations, isPending } = useImportableIntegrations();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [step, setStep] = useState<"select" | "import">("select");

  const firstConnected = integrations.find((entry) => entry.connected) ?? null;
  const selected =
    integrations.find((entry) => entry.tenant_integration_id === selectedId) ?? firstConnected;

  const settingsHref = space.personal ? "/account/integrations" : null;

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
                  {t("personal_account")}
                </Link>
              )}
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            {isPending ? (
              <div className="text-muted-foreground flex items-center justify-center gap-2 py-8">
                <Spinner /> {t("loading_integrations")}
              </div>
            ) : integrations.length === 0 ? (
              <p className="text-muted-foreground py-8 text-center text-sm">
                {t("no_integrations_available")}
              </p>
            ) : (
              integrations.map((integration) => (
                <IntegrationCard
                  key={integration.tenant_integration_id}
                  integration={integration}
                  selected={selected?.tenant_integration_id === integration.tenant_integration_id}
                  onSelect={() => setSelectedId(integration.tenant_integration_id)}
                />
              ))
            )}
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
