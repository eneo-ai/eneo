import type { Eneo } from "@eneo/eneo-js";
import { createContext } from "./context";

const [getEneo, setEneo] = createContext<Eneo>("Authenticated eneo client");

function initEneo(data: { eneo: Eneo }) {
  setEneo(data.eneo);
}

export { initEneo, getEneo };
