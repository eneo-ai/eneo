import Image, { type StaticImageData } from "next/image";
import type { IntegrationKnowledge } from "../knowledge";
import confluenceLogo from "./confluence.png";
import sharepointLogo from "./sharepoint.png";

type IntegrationType = IntegrationKnowledge["integration_type"];

/** Per-vendor display metadata; all label values are i18n keys. */
export const VENDOR: Record<
  IntegrationType,
  { logo: StaticImageData; linkLabel: string; importHint: string }
> = {
  sharepoint: {
    logo: sharepointLogo,
    linkLabel: "open_in_sharepoint",
    importHint: "sharepoint_import_hint"
  },
  confluence: {
    logo: confluenceLogo,
    linkLabel: "open_in_confluence",
    importHint: "confluence_import_hint"
  }
};

export function VendorIcon({ type, size = 16 }: { type: IntegrationType; size?: number }) {
  return (
    <Image src={VENDOR[type].logo} alt={type} width={size} height={size} className="shrink-0" />
  );
}
