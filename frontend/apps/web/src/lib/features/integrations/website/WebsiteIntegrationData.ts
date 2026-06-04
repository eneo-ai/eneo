import type { IntegrationData } from "../IntegrationData";
import websiteImgUrl from "./website.svg";
import WebsiteIntegrationPlaceholderDialog from "./WebsiteIntegrationPlaceholderDialog.svelte";

export const WebsiteIntegrationData: IntegrationData = {
  logo: websiteImgUrl,
  descriptionKey: "website_integration_description",
  displayName: "Website",
  importHint: "Website integrations create website knowledge sources from a sitemap",
  ImportDialog: WebsiteIntegrationPlaceholderDialog,
  previewLinkLabel: "Open website"
};
