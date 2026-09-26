import { config } from "zod";

// Runs in the browser before the app hydrates (Next.js instrumentation-client).
//
// The production CSP has no 'unsafe-eval' (src/proxy.ts). On the first object
// parse Zod probes for eval with `new Function("")` to compile faster parsers;
// the probe fails safely but still reports a CSP violation. Zod's documented
// switch for strict CSPs skips the probe. The AI SDK parses its chat stream
// with the same Zod.
config({ jitless: true });
