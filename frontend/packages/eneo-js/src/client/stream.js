import { PartialError } from "./client";
import { getBytes, getLines, getMessages } from "./parse";

/**
 * Reading a ResponseStream and running a callback on every received message
 * @param {Response} response
 * @param {Object} callbacks
 * @param {(response: Response) => Promise<void>} [callbacks.onOpen]
 * @param {(ev: { id: string; event: string; data: string }) => void} [callbacks.onMessage]
 * @param {() => void} [callbacks.onClose]
 */
export async function readEvents(response, { onOpen, onMessage, onClose }) {
  if (response.ok) {
    if (onOpen) await onOpen?.(response);

    await getBytes(
      response.body,
      getLines(
        getMessages(
          () => {},
          () => {},
          onMessage ?? (() => {})
        )
      )
    );

    onClose?.();
    return true;
  } else {
    throw new PartialError("RESPONSE", response.status, await response.json());
  }
}
