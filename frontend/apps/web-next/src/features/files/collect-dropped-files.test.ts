import { describe, expect, it } from "vitest";
import { collectDroppedFiles } from "./collect-dropped-files";

function fileEntry(file: File): FileSystemEntry {
  return {
    isFile: true,
    isDirectory: false,
    file: (resolve: (value: File) => void) => resolve(file)
  } as FileSystemFileEntry;
}

function directoryEntry(...batches: FileSystemEntry[][]): FileSystemEntry {
  let next = 0;
  return {
    isFile: false,
    isDirectory: true,
    createReader: () => ({
      readEntries: (resolve: (entries: FileSystemEntry[]) => void) => resolve(batches[next++] ?? [])
    })
  } as FileSystemDirectoryEntry;
}

function dropped(entries: (FileSystemEntry | null)[], files: File[] = []): DataTransfer {
  return {
    items: entries.map((entry) => ({ webkitGetAsEntry: () => entry })),
    files
  } as unknown as DataTransfer;
}

describe("collectDroppedFiles", () => {
  it("reads nested folders and every directory batch", async () => {
    const files = [
      { name: "first.pdf" } as File,
      { name: "nested.txt" } as File,
      { name: "later.csv" } as File
    ];
    const nested = directoryEntry([fileEntry(files[1]!)], []);
    const folder = directoryEntry([fileEntry(files[0]!), nested], [fileEntry(files[2]!)], []);

    expect(await collectDroppedFiles(dropped([folder]))).toEqual(files);
  });

  it("falls back to the browser file list when folder entries are unavailable", async () => {
    const file = { name: "direct.pdf" } as File;
    expect(await collectDroppedFiles(dropped([null], [file]))).toEqual([file]);
  });
});
