/**
 *  This is a Work-in-progress concept for adding websockets
 */

import type { EneoSocket } from "@eneo/eneo-js";
import { createContext } from "./context";

const [getEneoSocket, setEneoSocket] = createContext<EneoSocket>("Authenticated eneo socket");

function initEneoSocket(data: { eneoSocket: EneoSocket }) {
  setEneoSocket(data.eneoSocket);
  return data.eneoSocket;
}

export { initEneoSocket, getEneoSocket };
