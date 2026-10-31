import { config } from "zod";

// Strict frame CSP also reports Zod's caught eval probe. Configure it before SDK schemas exist.
config({ jitless: true });
