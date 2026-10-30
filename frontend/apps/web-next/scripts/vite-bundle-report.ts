import { mkdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { normalizePath, type Plugin, type Rolldown } from "vite";

interface ChunkReport {
  fileName: string;
  bytes: number;
  imports: string[];
  dynamicImports: string[];
  modules: Record<string, number>;
}

interface ScopeReport {
  roots: string[];
  chunks: string[];
  modules: string[];
  bytes: number;
}

export interface BundleReport {
  chunks: ChunkReport[];
  scopes: { startup: ScopeReport; chat: ScopeReport | null };
}

/** Module ownership and static edges enforce feature boundaries independently of chunk names. */
export function bundleReport(): Plugin {
  let root: string;
  let reportPath: string;
  return {
    name: "eneo-bundle-report",
    apply: "build",
    configResolved(config) {
      root = config.root;
      // Keep module paths out of the deployed assets, but available to CI.
      reportPath = path.join(root, "node_modules/.cache/vite-bundle-report.json");
    },
    async buildStart() {
      // A failed rebuild must not publish an earlier successful report.
      await rm(reportPath, { force: true });
    },
    async writeBundle(_options, bundle) {
      const output = Object.values(bundle).filter(
        (chunk): chunk is Rolldown.OutputChunk => chunk.type === "chunk"
      );
      const moduleId = (id: string) =>
        normalizePath(path.isAbsolute(id) ? path.relative(root, id) : id);
      const chunks = output
        .map((chunk): ChunkReport => ({
          fileName: chunk.fileName,
          bytes: Buffer.byteLength(chunk.code, "utf8"),
          imports: [...chunk.imports].sort(),
          dynamicImports: [...chunk.dynamicImports].sort(),
          modules: Object.fromEntries(
            Object.entries(chunk.modules)
              .map(([id, module]) => [moduleId(id), module.renderedLength] as const)
              .sort(([a], [b]) => a.localeCompare(b))
          )
        }))
        .sort((a, b) => a.fileName.localeCompare(b.fileName));
      const byName = new Map(chunks.map((chunk) => [chunk.fileName, chunk]));
      const owns = (chunk: ChunkReport, source: string) =>
        Object.keys(chunk.modules).some((id) => id.split("?")[0] === source);
      const closure = (roots: string[]): ScopeReport => {
        const seen = new Set<string>();
        const pending = [...roots];
        while (pending.length) {
          const file = pending.pop()!;
          const chunk = byName.get(file);
          if (!chunk || seen.has(file)) continue;
          seen.add(file);
          pending.push(...chunk.imports);
        }
        const selected = chunks.filter((chunk) => seen.has(chunk.fileName));
        return {
          roots: roots.sort(),
          chunks: [...seen].sort(),
          modules: [...new Set(selected.flatMap((chunk) => Object.keys(chunk.modules)))].sort(),
          bytes: selected.reduce((bytes, chunk) => bytes + chunk.bytes, 0)
        };
      };
      const entries = new Set(
        output.filter((chunk) => chunk.isEntry).map((chunk) => chunk.fileName)
      );
      // render-app is required boot UI, despite main's nonce/config-driven dynamic import.
      const startup = chunks.filter(
        (chunk) => entries.has(chunk.fileName) || owns(chunk, "src/render-app.tsx")
      );
      const chat = chunks.filter((chunk) => owns(chunk, "src/features/chat/chat-page.tsx"));
      const report: BundleReport = {
        chunks,
        scopes: {
          startup: closure(startup.map((chunk) => chunk.fileName)),
          chat: chat.length ? closure(chat.map((chunk) => chunk.fileName)) : null
        }
      };
      await mkdir(path.dirname(reportPath), { recursive: true });
      await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n");

      for (const [name, scope] of Object.entries(report.scopes)) {
        const eager = scope?.modules.filter(
          (id) =>
            /(?:^|\/)node_modules\/(?:driver\.js|@tiptap\/[^/]+|prosemirror-[^/]+|rehype-stringify)\//.test(
              id
            ) || id.split("?")[0] === "src/components/ai-elements/answer-clipboard.ts"
        );
        if (eager?.length) {
          this.error(`Eager feature dependencies in ${name}:\n${eager.join("\n")}`);
        }
      }
    }
  };
}
