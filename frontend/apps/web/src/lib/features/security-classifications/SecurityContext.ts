/*
    Copyright (c) 2024 Sundsvalls Kommun
*/

import { createContext } from "$lib/core/context";
import type { Eneo } from "@eneo/eneo-js";

type SecurityContext = Awaited<ReturnType<Eneo["securityClassifications"]["list"]>>;

export const [getSecurityContext, setSecurityContext] = createContext<SecurityContext>("security");
