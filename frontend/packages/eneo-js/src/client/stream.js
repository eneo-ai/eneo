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

    /** @param {{ id: string; event: string; data: string }} message */
    const handleMessage = (message) => {
      if (isEmptySseFrame(message)) return;
      (onMessage ?? (() => {}))(message);
    };

    await getBytes(
      response.body,
      getLines(
        getMessages(
          () => {},
          () => {},
          handleMessage
        )
      )
    );

    onClose?.();
    return true;
  } else {
    throw new PartialError("RESPONSE", response.status, await response.json());
  }
}

/**
 * @param {{ id: string; event: string; data: string }} message
 * @returns {boolean}
 */
function isEmptySseFrame(message) {
  return message.event === "" && message.data === "" && message.id === "";
}
