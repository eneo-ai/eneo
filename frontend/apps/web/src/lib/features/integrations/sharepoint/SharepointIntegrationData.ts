import type { IntegrationData } from "../IntegrationData";
import sharepointImgUrl from "./sharepoint.png";
import SharepointImportDialog from "./SharepointImportDialog.svelte";

export const SharepointIntegrationData: IntegrationData = {
  logo: sharepointImgUrl,
  descriptionKey: "sharepoint_integration_description",
  displayName: "Sharepoint",
  importHint: "Import a site from Sharepoint",
  ImportDialog: SharepointImportDialog,
  previewLinkLabel: "open_in_sharepoint"
};
