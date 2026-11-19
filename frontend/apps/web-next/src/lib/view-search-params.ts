import { createContext } from "react";

/**
 * The search parameters that only choose a view of the page under it (a tab,
 * an item opened in place), for its leave guards (`useLeaveConfirmation`):
 * going from one view to another, Back and Forward included, keeps the page
 * mounted with everything in it, so no guard asks. A change of anything else
 * in the address still counts as leaving.
 */
export const ViewSearchParams = createContext<readonly string[]>([]);
