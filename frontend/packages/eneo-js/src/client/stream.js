import { PartialError } from "./client.js";
import { getBytes, getLines, getMessages } from "./parse.js";

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
    // A gateway in front of the backend answers with an HTML page; its markup
    // is no message for a user, so the caller's generic message applies.
    let parsed;
    try {
      parsed = await response.json();
    } catch {
      parsed = { message: "", eneo_error_code: 0 };
    }
    throw new PartialError("RESPONSE", response.status, parsed);
  }
}
