// @vitest-environment jsdom
import { act, waitFor } from "@testing-library/react";
import type { DragEvent } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderHookInApp } from "@/test/render";
import { useFileDrop } from "./use-file-drop";

const toastError = vi.hoisted(() => vi.fn());
vi.mock("@/lib/toast", () => ({ toast: { error: toastError } }));

afterEach(() => vi.clearAllMocks());

function fileEntry(file: File): FileSystemEntry {
  return {
    isFile: true,
    isDirectory: false,
    file: (resolve: (value: File) => void) => resolve(file)
  } as FileSystemFileEntry;
}

function directoryEntry(...children: FileSystemEntry[]): FileSystemEntry {
  let read = false;
  return {
    isFile: false,
    isDirectory: true,
    createReader: () => ({
      readEntries: (resolve: (entries: FileSystemEntry[]) => void) => {
        resolve(read ? [] : children);
        read = true;
      }
    })
  } as FileSystemDirectoryEntry;
}

function dragEvent({
  types = ["Files"],
  entries = []
}: { types?: string[]; entries?: FileSystemEntry[] } = {}) {
  return {
    preventDefault: vi.fn(),
    dataTransfer: {
      types,
      dropEffect: "none",
      items: entries.map((entry) => ({ webkitGetAsEntry: () => entry })),
      files: []
    }
  } as unknown as DragEvent & { preventDefault: ReturnType<typeof vi.fn> };
}

/** Lets the drop's async folder read settle. */
const settle = () => act(() => new Promise((resolve) => setTimeout(resolve, 0)));

describe("useFileDrop", () => {
  it("hands over the files inside a dropped folder", async () => {
    const onFiles = vi.fn();
    const files = [new File(["a"], "a.txt"), new File(["b"], "b.txt")];
    const { result } = renderHookInApp(() => useFileDrop(onFiles));

    act(() => result.current.handlers.onDragEnter(dragEvent()));
    expect(result.current.dragging).toBe(true);
    const drop = dragEvent({
      entries: [directoryEntry(fileEntry(files[0]!), directoryEntry(fileEntry(files[1]!)))]
    });
    act(() => result.current.handlers.onDrop(drop));

    expect(drop.preventDefault).toHaveBeenCalled();
    expect(result.current.dragging).toBe(false);
    await waitFor(() => expect(onFiles).toHaveBeenCalledWith(files));
  });

  it("stays highlighted while the drag crosses a child element", () => {
    const { result } = renderHookInApp(() => useFileDrop(vi.fn()));
    const { onDragEnter, onDragLeave } = result.current.handlers;

    act(() => onDragEnter(dragEvent())); // the zone
    act(() => onDragEnter(dragEvent())); // a child inside it
    act(() => onDragLeave(dragEvent())); // the zone, on the way into the child
    expect(result.current.dragging).toBe(true);

    act(() => onDragLeave(dragEvent())); // the child, out of the zone
    expect(result.current.dragging).toBe(false);
  });

  it("ignores a text drag", async () => {
    const onFiles = vi.fn();
    const { result } = renderHookInApp(() => useFileDrop(onFiles));
    const { onDragEnter, onDragOver, onDrop } = result.current.handlers;
    const events = [dragEvent({ types: ["text/plain"] }), dragEvent({ types: ["text/plain"] })];

    act(() => onDragEnter(events[0]!));
    act(() => onDragOver(events[1]!));
    expect(result.current.dragging).toBe(false);
    act(() => onDrop(dragEvent({ types: ["text/plain"] })));
    await settle();

    for (const event of events) expect(event.preventDefault).not.toHaveBeenCalled();
    expect(onFiles).not.toHaveBeenCalled();
  });

  it("does nothing for a drop without files", async () => {
    const onFiles = vi.fn();
    const { result } = renderHookInApp(() => useFileDrop(onFiles));

    act(() => result.current.handlers.onDrop(dragEvent({ entries: [directoryEntry()] })));
    await settle();

    expect(onFiles).not.toHaveBeenCalled();
    expect(toastError).not.toHaveBeenCalled();
  });

  it("claims a file drag without taking the files while disabled", async () => {
    const onFiles = vi.fn();
    const { result } = renderHookInApp(() => useFileDrop(onFiles, { enabled: false }));
    const over = dragEvent();

    act(() => result.current.handlers.onDragEnter(dragEvent()));
    act(() => result.current.handlers.onDragOver(over));
    expect(result.current.dragging).toBe(false);
    // Claimed, so the browser does not open the file in place of the app.
    expect(over.preventDefault).toHaveBeenCalled();
    expect(over.dataTransfer.dropEffect).toBe("none");

    act(() =>
      result.current.handlers.onDrop(dragEvent({ entries: [fileEntry(new File([], "x"))] }))
    );
    await settle();
    expect(onFiles).not.toHaveBeenCalled();
  });

  it("reports a drop that cannot be read with the upload error toast, or to onError", async () => {
    const unreadable = {
      isFile: true,
      isDirectory: false,
      file: (_resolve: unknown, reject: (error: Error) => void) => reject(new Error("denied"))
    } as unknown as FileSystemEntry;
    const onFiles = vi.fn();

    const { result } = renderHookInApp(() => useFileDrop(onFiles));
    act(() => result.current.handlers.onDrop(dragEvent({ entries: [unreadable] })));
    await waitFor(() => expect(toastError).toHaveBeenCalledWith("Fel vid filuppladdning"));

    const onError = vi.fn();
    const custom = renderHookInApp(() => useFileDrop(onFiles, { onError }));
    act(() => custom.result.current.handlers.onDrop(dragEvent({ entries: [unreadable] })));
    await waitFor(() => expect(onError).toHaveBeenCalledWith(new Error("denied")));
    expect(toastError).toHaveBeenCalledTimes(1);
    expect(onFiles).not.toHaveBeenCalled();
  });
});
