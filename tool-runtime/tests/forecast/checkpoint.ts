import { join } from "node:path";
import { FORECAST_PYTHON } from "../../src/tools/forecast/engine/timestral";

/** A tiny Timestral checkpoint with random weights: real code paths, no published weights. */
export async function tinyCheckpoint(directory: string): Promise<string> {
  const path = join(directory, "tiny");
  const script = `
import sys, torch
from safetensors.torch import save_file
from timestral import TimestralConfig, TimestralModel
config = TimestralConfig(patch_size=8, d_model=32, num_heads=4, mlp_hidden_dim=64,
    block_schedule=("time", "time_variate", "time", "time_variate"),
    quantile_knots=(0.05, 0.1, 0.25, 0.4, 0.5, 0.6, 0.75, 0.9, 0.95), block_size=4, context_length=512)
torch.manual_seed(0)
model = TimestralModel(config)
for p in model.parameters():
    torch.nn.init.normal_(p, std=0.05)
import pathlib
out = pathlib.Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
config.save(out / "config.json")
save_file({k: v.contiguous() for k, v in model.state_dict().items()}, str(out / "model.safetensors"))
`;
  const child = Bun.spawn([FORECAST_PYTHON, "-I", "-c", script, path], { stderr: "pipe" });
  if ((await child.exited) !== 0) throw new Error(await new Response(child.stderr).text());
  return path;
}
