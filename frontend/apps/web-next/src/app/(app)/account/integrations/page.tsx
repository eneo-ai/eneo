import { pageTitle } from "@/lib/page-metadata";
import { AccountIntegrations } from "./integrations.client";

export const generateMetadata = pageTitle("my_integrations");

export default function AccountIntegrationsPage() {
  return <AccountIntegrations />;
}
