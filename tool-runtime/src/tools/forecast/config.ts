import { z } from "zod";

/**
 * Limits of one forecast. They keep one call inside Eneo's tool-call timeout and its result
 * inside the model's text budget: the horizon and the plotted history bound what is returned,
 * the history cap bounds what the model reads.
 */
export const forecastConfigSchema = z
  .object({
    /** A checkpoint directory (`config.json` + `model.safetensors`) the operator mounted. */
    model_path: z.string().min(1),
    /** Shown to the user as the model that made the forecast. */
    model_name: z.string().min(1).max(80).default("Timestral"),
    max_horizon_days: z.number().int().min(1).max(366).default(180),
    max_history_days: z.number().int().min(60).max(32_768).default(4096),
    min_history_days: z.number().int().min(14).max(366).default(28),
    /** Share of days in the history that may lack a value. */
    max_missing_share: z.number().min(0).max(0.5).default(0.2),
    plot_history_days: z.number().int().min(14).max(1000).default(180),
    threads: z.number().int().min(1).max(16).default(2),
  })
  .strict();
export type ForecastConfig = z.infer<typeof forecastConfigSchema>;
