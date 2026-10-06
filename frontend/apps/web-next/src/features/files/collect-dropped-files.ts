/** Resolve files dropped from a browser file list or nested folders. */
export async function collectDroppedFiles(dataTransfer: DataTransfer): Promise<File[]> {
  // Capture entries before the first await; browsers clear DataTransfer after drop.
  const entries = Array.from(dataTransfer.items, (item) => item.webkitGetAsEntry?.() ?? null);
  if (entries.every((entry) => entry === null)) return Array.from(dataTransfer.files);

  const collected: File[] = [];
  for (const entry of entries) {
    if (entry) await collectEntry(entry, collected);
  }
  return collected;
}

async function collectEntry(entry: FileSystemEntry, into: File[]): Promise<void> {
  if (entry.isFile) {
    const file = await new Promise<File>((resolve, reject) =>
      (entry as FileSystemFileEntry).file(resolve, reject)
    );
    into.push(file);
    return;
  }
  if (entry.isDirectory) {
    const reader = (entry as FileSystemDirectoryEntry).createReader();
    // readEntries may yield only a batch, so read until the directory is empty.
    for (;;) {
      const batch = await new Promise<FileSystemEntry[]>((resolve, reject) =>
        reader.readEntries(resolve, reject)
      );
      if (batch.length === 0) break;
      for (const child of batch) await collectEntry(child, into);
    }
  }
}
