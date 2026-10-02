/**
 * Convert an XLSX workbook's bytes into a CSV per sheet. Used at ingest
 * time only — once converted, every downstream concern (schema describe,
 * row queries) goes through DuckDB's `read_csv_auto` against the resulting
 * CSV blobs, so the runtime query path stays format-agnostic.
 *
 * Why a one-shot conversion at ingest instead of querying XLSX directly
 * via DuckDB's `excel` community extension: the extension ships separately,
 * needs network install on first use, and adds a runtime dependency we'd
 * have to manage per platform. Converting once at ingest keeps the query
 * path lean and predictable.
 *
 * Uses ExcelJS (MIT) to parse the workbook. The CSV itself is written here
 * rather than by ExcelJS's `csv.writeBuffer`: that writer emits each row as
 * wide as its own last cell, so a header with a stray whitespace cell (an
 * exporter habit) comes out one field wider than the data rows below it, and
 * DuckDB then rejects every data row as malformed — a 14,000-row sheet
 * ingested as zero rows. Rows are padded to one shared width, trailing
 * blank-only columns are dropped, and blank rows are skipped.
 */
import ExcelJS from "exceljs";
import { ToolError } from "../../../errors";
import type { SourceSelection } from "../selection";
import type { CalculationDiagnostics } from "../ports";
import JSZip from "jszip";
import { SaxesParser } from "saxes";
import { posix } from "node:path";
import { assertZipWithinBounds } from "../zip-guard";

export type SheetCsv = {
  /** User-visible sheet name as it appears in Excel. */
  name: string;
  /** UTF-8 CSV bytes ready to write to S3. */
  csv: Buffer;
  calculation?: CalculationDiagnostics;
  sourceRows?: number[];
  explicitHeader?: boolean;
};

/** Excel's own ceiling for a worksheet name. */
const MAX_SHEET_NAME_LENGTH = 31;

/**
 * Parse XLSX bytes and emit a CSV blob per sheet, preserving workbook order.
 * Skips fully-empty sheets (those produce zero-byte CSVs and would just
 * confuse the LLM later).
 */
export async function convertXlsxToCsvSheets(
  xlsxBytes: Buffer,
  selection?: SourceSelection,
): Promise<SheetCsv[]> {
  // XLSX is a zip; refuse decompression bombs before ExcelJS inflates it.
  assertZipWithinBounds(xlsxBytes);
  const { bytes, originalNames } = await normalizeSheetNames(xlsxBytes);
  const workbook = new ExcelJS.Workbook();
  // ExcelJS ships an older un-parameterized `Buffer` type that TS can't
  // reconcile with modern `Buffer<ArrayBufferLike>` — same runtime value,
  // type cast is purely to satisfy the outdated upstream signature.
  await workbook.xlsx.load(bytes as unknown as Parameters<typeof workbook.xlsx.load>[0]);

  const emptyResults = await emptyFormulaResults(bytes);
  const out: SheetCsv[] = [];
  const requested = selection
    ? workbook.worksheets.filter(
        (sheet) =>
          !selection.sheet ||
          (originalNames.get(sheet.name.toLowerCase()) ?? sheet.name) === selection.sheet,
      )
    : workbook.worksheets;
  if (selection && requested.length !== 1)
    throw new ToolError("UNKNOWN_SHEET", "Select one exact worksheet from the original file.");
  for (const worksheet of requested) {
    // ExcelJS counts rows even when they contain only stylings; `rowCount`
    // includes the trailing empty rows that operators sometimes leave. We
    // skip a sheet only when its actual row range is empty.
    if (selection && selection.source_rows.some((row) => row > worksheet.rowCount))
      throw new ToolError(
        "INVALID_SELECTION",
        "A selected source row is outside the worksheet. Reopen the file and select again.",
      );
    if (worksheet.actualRowCount === 0) continue;

    const empty = emptyResults.get(worksheet.name) ?? new Set<string>();
    const calculation: CalculationDiagnostics = {
      formula_cells: 0,
      missing_cached_results: 0,
      recalculated: false,
    };
    worksheet.eachRow((row) =>
      row.eachCell((cell) => {
        if (selection && !selection.source_rows.includes(row.number)) return;
        const value = cellValue(cell, empty);
        if (
          value &&
          typeof value === "object" &&
          ("formula" in value || "sharedFormula" in value)
        ) {
          calculation.formula_cells++;
          if (value.result === undefined || value.result === null)
            calculation.missing_cached_results++;
        }
      }),
    );
    const csv = worksheetToCsv(worksheet, empty, selection?.source_rows);
    // Retain diagnostics even when every cell is an uncalculated formula.
    if (csv === null && calculation.formula_cells === 0) continue;
    out.push({
      name: originalNames.get(worksheet.name.toLowerCase()) ?? worksheet.name,
      csv: csv ?? Buffer.alloc(0),
      ...(selection ? { sourceRows: selection.source_rows, explicitHeader: true } : {}),
      ...(calculation.formula_cells ? { calculation } : {}),
    });
  }
  return out;
}

/**
 * RFC 4180 CSV for one worksheet, every row the same width. Returns null
 * when nothing but blanks remain. Cell values fold the way ExcelJS's own
 * CSV writer folds them (rich text → text, hyperlink → target, formula →
 * cached result, error → its code), so a workbook that converted before
 * converts the same way now, minus the ragged rows.
 */
function worksheetToCsv(
  worksheet: ExcelJS.Worksheet,
  empty: Set<string>,
  sourceRows?: number[],
): Buffer | null {
  if (sourceRows) {
    // Read immutable source coordinates before dropping blanks or inferring a header.
    const width = worksheet.columnCount;
    if (width > 200)
      throw new ToolError("INVALID_SELECTION", "The selection has too many columns (maximum 200).");
    return Buffer.from(
      [1, ...sourceRows]
        .map((number) => {
          const row = worksheet.getRow(number);
          return Array.from({ length: width }, (_, column) => {
            const text = cellToText(cellValue(row.getCell(column + 1), empty));
            return '"' + text.replaceAll('"', '""') + '"';
          }).join(",");
        })
        .join("\r\n") + "\r\n",
    );
  }
  const rows: string[][] = [];
  let width = 0;
  worksheet.eachRow({ includeEmpty: false }, (row) => {
    // `row.values` is 1-based: index 0 is always empty.
    const values = Array<string>(row.cellCount).fill("");
    row.eachCell((cell, column) => {
      values[column - 1] = cellToText(cellValue(cell, empty));
    });
    if (!values.some((v) => v.trim() !== "")) return;
    rows.push(values);
    for (let i = values.length - 1; i >= 0; i--) {
      if (values[i]!.trim() !== "") {
        width = Math.max(width, i + 1);
        break;
      }
    }
  });
  if (rows.length === 0 || width === 0) return null;

  const lines = rows.map((values) => {
    const padded = Array.from({ length: width }, (_, i) => values[i] ?? "");
    return padded.map(csvField).join(",");
  });
  return Buffer.from(lines.join("\n") + "\n", "utf8");
}

/**
 * ExcelJS's value getter omits falsy formula results. Its parsed model retains
 * zero and false; explicit empty-string caches need the worksheet XML because
 * the parser discards empty <v> text too.
 */
function cellValue(cell: ExcelJS.Cell, empty: Set<string>): ExcelJS.CellValue {
  const value = cell.value;
  if (value && typeof value === "object" && ("formula" in value || "sharedFormula" in value)) {
    const result = empty.has(cell.address)
      ? ""
      : (cell.model as { result?: ExcelJS.CellValue }).result;
    return { ...value, result } as ExcelJS.CellValue;
  }
  return value;
}

/** Read only cache presence, never execute formulas or load external resources. */
async function emptyFormulaResults(bytes: Buffer): Promise<Map<string, Set<string>>> {
  const zip = await JSZip.loadAsync(bytes);
  const relations = new Map<string, string>();
  const sheets = new Map<string, string>();
  function parse(
    xml: string,
    open: (name: string, attrs: Record<string, string>) => void,
    close: (name: string) => void = () => {},
    text: (value: string) => void = () => {},
  ) {
    const parser = new SaxesParser();
    parser.on("opentag", (tag) => open(tag.name.split(":").at(-1)!, tag.attributes));
    parser.on("closetag", (tag) => close(tag.name.split(":").at(-1)!));
    parser.on("text", text);
    parser.write(xml).close();
  }
  parse(await zip.file("xl/_rels/workbook.xml.rels")!.async("string"), (name, attrs) => {
    if (name === "Relationship" && attrs.TargetMode !== "External") {
      const target = attrs.Target?.startsWith("/")
        ? attrs.Target.slice(1)
        : posix.join("xl", attrs.Target ?? "");
      if (target.startsWith("xl/")) relations.set(attrs.Id!, target);
    }
  });
  parse(await zip.file("xl/workbook.xml")!.async("string"), (name, attrs) => {
    if (name === "sheet") sheets.set(attrs.name!, attrs["r:id"]!);
  });
  const result = new Map<string, Set<string>>();
  for (const [name, relation] of sheets) {
    const entry = zip.file(relations.get(relation) ?? "");
    if (!entry) continue;
    const empty = new Set<string>();
    let address = "",
      stringCell = false,
      formula = false,
      hasValue = false,
      value = "",
      inValue = false;
    parse(
      await entry.async("string"),
      (tag, attrs) => {
        if (tag === "c") {
          address = attrs.r ?? "";
          stringCell = attrs.t === "str";
          formula = false;
          hasValue = false;
          value = "";
        }
        if (tag === "f") formula = true;
        if (tag === "v") {
          hasValue = true;
          inValue = true;
        }
      },
      (tag) => {
        if (tag === "v") inValue = false;
        if (tag === "c" && formula && stringCell && hasValue && value === "") empty.add(address);
      },
      (text) => {
        if (inValue) value += text;
      },
    );
    result.set(name, empty);
  }
  return result;
}

function cellToText(value: ExcelJS.CellValue): string {
  if (value === null || value === undefined) return "";
  if (value instanceof Date) return value.toISOString();
  if (typeof value === "object") {
    if ("richText" in value) return value.richText.map((run) => run.text).join("");
    if ("hyperlink" in value) return value.hyperlink || value.text || "";
    if ("formula" in value || "sharedFormula" in value) {
      return value.result === undefined || value.result === null ? "" : cellToText(value.result);
    }
    if ("error" in value) return value.error;
    return JSON.stringify(value);
  }
  return String(value);
}

function csvField(value: string): string {
  return /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

/**
 * Excel caps a sheet name at 31 characters and forbids case-insensitive
 * duplicates, but files written by other systems (billing exports, ERP
 * dumps) routinely carry longer names. ExcelJS truncates such a name in the
 * worksheet constructor, then re-applies the full name from the parsed
 * model, and its duplicate check finds the worksheet ITSELF — the load
 * throws "Worksheet name already exists". Rewriting the names inside
 * `xl/workbook.xml` before ExcelJS sees them sidesteps that; the original
 * name is kept so the operator still sees the sheet as the file calls it.
 * A workbook whose names are already within bounds is passed through
 * untouched.
 */
async function normalizeSheetNames(
  xlsxBytes: Buffer,
): Promise<{ bytes: Buffer; originalNames: Map<string, string> }> {
  const originalNames = new Map<string, string>();
  const zip = await JSZip.loadAsync(xlsxBytes);
  const entry = zip.file("xl/workbook.xml");
  if (!entry) return { bytes: xlsxBytes, originalNames };

  const xml = await entry.async("string");
  const taken = new Set<string>();
  let changed = false;
  const rewritten = xml.replace(
    /(<sheet\b[^>]*?\sname=")([^"]*)(")/g,
    (match, prefix: string, rawName: string, suffix: string) => {
      const original = decodeXmlAttribute(rawName);
      const safe = uniqueSheetName(original, taken);
      taken.add(safe.toLowerCase());
      if (safe === original) return match;
      changed = true;
      originalNames.set(safe.toLowerCase(), original);
      return `${prefix}${encodeXmlAttribute(safe)}${suffix}`;
    },
  );
  if (!changed) return { bytes: xlsxBytes, originalNames };

  zip.file("xl/workbook.xml", rewritten);
  const bytes = await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" });
  return { bytes, originalNames };
}

/** Truncate to Excel's limit, then suffix ` (2)`, ` (3)`, … until unique (case-insensitive). */
function uniqueSheetName(name: string, taken: ReadonlySet<string>): string {
  const base = name.slice(0, MAX_SHEET_NAME_LENGTH);
  if (!taken.has(base.toLowerCase())) return base;
  for (let n = 2; ; n++) {
    const suffix = ` (${n})`;
    const candidate = base.slice(0, MAX_SHEET_NAME_LENGTH - suffix.length) + suffix;
    if (!taken.has(candidate.toLowerCase())) return candidate;
  }
}

function decodeXmlAttribute(value: string): string {
  return value
    .replace(/&#x([0-9a-fA-F]+);/g, (_, hex: string) => String.fromCodePoint(parseInt(hex, 16)))
    .replace(/&#(\d+);/g, (_, dec: string) => String.fromCodePoint(parseInt(dec, 10)))
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");
}

function encodeXmlAttribute(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
