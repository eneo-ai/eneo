import type { IntegrationData } from "../IntegrationData";
import sharepointImgUrl from "./sharepoint.png";
import SharepointImportDialog from "./SharepointImportDialog.svelte";
import { m } from "$lib/paraglide/messages";

export const SharepointIntegrationData: IntegrationData = {
  logo: sharepointImgUrl,
  descriptionKey: "sharepoint_integration_description",
  displayName: "SharePoint",
  importHint: "Import a site from SharePoint",
  ImportDialog: SharepointImportDialog,
  previewLinkLabel: m.open_in_sharepoint
};
