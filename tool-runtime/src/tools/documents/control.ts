/** Backend-owned deterministic rendering using the same sandbox engine as MCP. */
import { z } from "zod";
import { ToolError } from "../../errors";
import type { Renderer } from "./tool";
import { MIME_BY_FORMAT } from "./filename";

const MAX_TEMPLATE_BYTES = 5 * 1024 * 1024;
const template = z
  .string()
  .max(Math.ceil(MAX_TEMPLATE_BYTES / 3) * 4)
  .optional();
const requestSchema = z.discriminatedUnion("mode", [
  z
    .object({
      mode: z.literal("render"),
      format: z.enum(["docx", "pdf"]),
      title: z.string().max(200),
      content: z.string().max(1_000_000),
      include_title: z.boolean().default(true),
      language: z.enum(["sv", "en"]).default("sv"),
      template,
    })
    .strict(),
  z
    .object({
      mode: z.literal("fill"),
      format: z.literal("docx"),
      template: z.string().max(Math.ceil(MAX_TEMPLATE_BYTES / 3) * 4),
      values: z.record(z.string().max(200), z.string().max(1_000_000)),
    })
    .strict(),
]);

export function documentControlRenderer(render: Renderer, maxBytes: number) {
  return async (input: unknown): Promise<{ buffer: Buffer; mimetype: string }> => {
    const parsed = requestSchema.safeParse(input);
    if (!parsed.success)
      throw new ToolError(
        "INVALID_INPUT",
        "The document request is invalid or exceeds its limits.",
      );
    const request = parsed.data;
    const bytes = request.template ? Buffer.from(request.template, "base64") : undefined;
    if (
      bytes &&
      (bytes.length > MAX_TEMPLATE_BYTES || bytes.toString("base64") !== request.template)
    )
      throw new ToolError("INVALID_TEMPLATE", "The template is invalid or exceeds its size limit.");
    if (
      request.mode === "fill" &&
      (!bytes ||
        Object.keys(request.values).length > 10_000 ||
        Object.values(request.values).reduce((n, value) => n + value.length, 0) > 1_000_000)
    )
      throw new ToolError("INVALID_INPUT", "The template values exceed their limits.");
    const document =
      request.mode === "fill"
        ? { kind: "fill" as const, template: { index: 0 }, values: request.values }
        : {
            kind: "markdown" as const,
            title: request.title,
            content: request.content,
            language: request.language,
            includeTitle: request.include_title,
            ...(bytes ? { template: { index: 0 } } : {}),
          };
    const result = await render({
      format: request.format,
      document,
      maxBytes,
      organisationName: "",
      ...(bytes ? { sources: [bytes] } : {}),
    });
    return { buffer: result.buffer, mimetype: MIME_BY_FORMAT[request.format] };
  };
}
