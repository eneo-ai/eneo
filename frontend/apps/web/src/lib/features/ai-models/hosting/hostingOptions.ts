/*
 * Copyright (c) 2026 Sundsvalls Kommun
 *
 * Single source of truth for the hosting-region options shown when adding
 * or editing a model. Mirrors the values accepted by the backend.
 */
import { m } from "$lib/paraglide/messages";

export type HostingValue =
  | "swe"
  | "eu"
  | "usa"
  | "chn"
  | "can"
  | "gbr"
  | "isr"
  | "kor"
  | "deu"
  | "fra"
  | "jpn";

export interface HostingOption {
  value: HostingValue;
  label: string;
}

export function listHostingOptions(): HostingOption[] {
  return [
    { value: "swe", label: m.hosting_swe() },
    { value: "eu", label: m.hosting_eu() },
    { value: "usa", label: m.hosting_usa() },
    { value: "chn", label: m.hosting_chn() },
    { value: "can", label: m.hosting_can() },
    { value: "gbr", label: m.hosting_gbr() },
    { value: "isr", label: m.hosting_isr() },
    { value: "kor", label: m.hosting_kor() },
    { value: "deu", label: m.hosting_deu() },
    { value: "fra", label: m.hosting_fra() },
    { value: "jpn", label: m.hosting_jpn() }
  ];
}

export function findHostingLabel(value: string | undefined): string {
  if (!value) return "";
  return listHostingOptions().find((o) => o.value === value)?.label ?? value;
}
