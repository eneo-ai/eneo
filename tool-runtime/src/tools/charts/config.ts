import { z } from "zod";

export const chartConfigSchema = z
  .object({
    width: z.number().int().min(400).max(2000).default(1200),
    height: z.number().int().min(300).max(1400).default(675),
    max_points: z.number().int().min(10).max(20_000).default(2000),
    // Base64 output travels through the sandbox child's bounded stdout; keep PNGs well below it.
    max_image_bytes: z
      .number()
      .int()
      .min(32 * 1024)
      .max(400 * 1024)
      .default(384 * 1024),
    number_locale: z.enum(["sv-SE", "en-GB"]).default("sv-SE"),
  })
  .strict();
export type ChartConfig = z.infer<typeof chartConfigSchema>;
