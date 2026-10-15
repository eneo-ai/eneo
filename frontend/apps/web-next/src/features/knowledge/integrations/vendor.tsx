import Image, { type StaticImageData } from "next/image";
import type { IntegrationKnowledge } from "../knowledge";
import confluenceLogo from "./confluence.png";
import sharepointLogo from "./sharepoint.png";

type IntegrationType = IntegrationKnowledge["integration_type"];

/** Per-vendor display metadata; all label values are i18n keys. */
export const VENDOR: Record<
  IntegrationType,
  { logo: StaticImageData; name: string; linkLabel: string; importHint: string }
> = {
  sharepoint: {
    logo: sharepointLogo,
    name: "integration_vendor_sharepoint",
    linkLabel: "open_in_sharepoint",
    importHint: "sharepoint_import_hint"
  },
  confluence: {
    logo: confluenceLogo,
    name: "integration_vendor_confluence",
    linkLabel: "open_in_confluence",
    importHint: "confluence_import_hint"
  }
};

/** The vendor's logo; decorative, since it always sits next to the item's or vendor's name. */
export function VendorIcon({ type, size = 16 }: { type: IntegrationType; size?: number }) {
  return <Image src={VENDOR[type].logo} alt="" width={size} height={size} className="shrink-0" />;
}
