import type { IntegrationData } from "../IntegrationData";
import confluenceImgUrl from "./confluence.png";
import ConfluenceImportDialog from "./ConfluenceImportDialog.svelte";
import { m } from "$lib/paraglide/messages";

export const ConfluenceIntegrationData: IntegrationData = {
  logo: confluenceImgUrl,
  descriptionKey: "confluence_integration_description",
  displayName: "Confluence",
  importHint: "Import a Confluence space into your knowledge",
  ImportDialog: ConfluenceImportDialog,
  previewLinkLabel: m.open_in_confluence
};
