import type { DateRange } from "@astryxdesign/core/DateRangeInput";
import type { ChatPartner } from "@/lib/chat/types";

/** A local calendar date as YYYY-MM-DD (Astryx's ISODateString). */
export type IsoDate = DateRange["start"];

/** The period insights cover: whole local days, both ends included. */
export type InsightRange = { start: IsoDate; end: IsoDate };

export const DEFAULT_INSIGHT_DAYS = 30;
export const INSIGHT_PRESET_DAYS = [7, 30, 90] as const;

export function isoDate(date: Date): IsoDate {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}` as IsoDate;
}

function shiftDays(date: Date, days: number): Date {
  const shifted = new Date(date);
  shifted.setDate(shifted.getDate() + days);
  return shifted;
}

/** The last `days` days up to and including today. */
export function insightRangeOfDays(days: number, now = new Date()): InsightRange {
  return { start: isoDate(shiftDays(now, -days)), end: isoDate(now) };
}

/** The date after `date`, as YYYY-MM-DD. */
export function nextDay(date: IsoDate): IsoDate {
  return isoDate(shiftDays(new Date(`${date}T00:00:00`), 1));
}

/**
 * The query parameters of the insight endpoints for a range. The end day is
 * included as a whole: the exclusive bound is the next day at 00:00, as the
 * Svelte app sends it (the backend reads a bare date as midnight).
 */
export function insightRangeParams(range: InsightRange): {
  /** Statistics: instants. */
  startTime: string;
  endTime: string;
  /** Sessions and analysis questions: calendar dates. */
  fromDate: IsoDate;
  toDate: IsoDate;
} {
  const toDate = nextDay(range.end);
  return {
    startTime: new Date(`${range.start}T00:00:00`).toISOString(),
    endTime: new Date(`${toDate}T00:00:00`).toISOString(),
    fromDate: range.start,
    toDate
  };
}

/** Which partner the insight endpoints are asked about. */
export function insightPartnerQuery(partner: Pick<ChatPartner, "type" | "id">): {
  assistant_id?: string;
  group_chat_id?: string;
} {
  if (partner.type === "group-chat") return { group_chat_id: partner.id };
  return { assistant_id: partner.id };
}
