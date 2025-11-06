import type { IntegrationData } from "../IntegrationData";
import sharepointImgUrl from "./sharepoint.png";
import SharepointImportDialog from "./SharepointImportDialog.svelte";

export const SharepointIntegrationData: IntegrationData = {
  logo: sharepointImgUrl,
  description: "This integration enables the seamless import of sites from Sharepoint into intric.",
  displayName: "Sharepoint",
  importHint: "Import a site from Sharepoint",
  ImportDialog: SharepointImportDialog,
  previewLinkLabel: "open_in_sharepoint"
};
