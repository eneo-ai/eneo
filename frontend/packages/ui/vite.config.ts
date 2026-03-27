import { sveltekit } from "@sveltejs/kit/vite";
import { defineConfig, type PluginOption } from "vite";
import { intricIcons } from "./src/icons/vite-plugin-eneo-icons";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [
    tailwindcss() as PluginOption,
    intricIcons() as PluginOption,
    sveltekit() as PluginOption
  ]
});
