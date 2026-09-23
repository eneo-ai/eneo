// Copyright (c) 2026 Sundsvalls Kommun

import { m } from "$lib/paraglide/messages";

/** "Primär indata vid körning: Dokument." → "Dokument".
 *
 *  The server states the input and the result as sentences. Beside a list of
 *  short decisions they read as boilerplate, so the recap keeps the thing that
 *  is named and drops the sentence around it.
 */
export function summaryTerm(sentence: string | null | undefined): string {
  const text = (sentence ?? "").trim();
  const named = text.includes(":") ? text.slice(text.indexOf(":") + 1) : text;
  return named.trim().replace(/[.\s]+$/, "");
}

/** A run-time field's type as the form editor names it ("Datum", not "date"). */
export function fieldTypeLabel(type: string): string {
  if (type === "number") return m.flow_form_field_type_number();
  if (type === "date") return m.flow_form_field_type_date();
  if (type === "select") return m.flow_form_field_type_select();
  if (type === "multiselect") return m.flow_form_field_type_multiselect();
  if (type === "list") return m.flow_form_field_type_list();
  return m.flow_form_field_type_text();
}
