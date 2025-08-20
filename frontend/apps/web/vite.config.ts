import { sveltekit } from "@sveltejs/kit/vite";
import { defineConfig } from "vitest/config";
import type { PluginOption } from "vite";
import tailwindcss from "@tailwindcss/vite";
// Visualiser to analyse bundle sizes
// import { visualizer } from "rollup-plugin-visualizer";

import { readFileSync, existsSync } from "fs";
import { fileURLToPath } from "url";
import { join, dirname } from "path";
import { intricIcons } from "@intric/ui/icons/vite-plugin-intric-icons";

const file = fileURLToPath(new URL("package.json", import.meta.url));
const json = readFileSync(file, "utf8");
const pkg = JSON.parse(json);

// Load environment variables from .env file
function loadEnvFile(): Record<string, string> {
  const envPath = join(dirname(fileURLToPath(import.meta.url)), '.env');
  if (!existsSync(envPath)) {
    return {};
  }
  
  const envContent = readFileSync(envPath, 'utf8');
  const env: Record<string, string> = {};
  
  for (const line of envContent.split('\n')) {
    const trimmed = line.trim();
    if (trimmed && !trimmed.startsWith('#') && trimmed.includes('=')) {
      const [key, ...valueParts] = trimmed.split('=');
      const value = valueParts.join('=').replace(/^["']|["']$/g, '');
      env[key.trim()] = value;
    }
  }
  
  // Merge with process.env (process.env takes precedence)
  return { ...env, ...process.env };
}

// Improved secret masking - fixed length for security
function maskSecret(value?: string): string {
  if (!value) {
    return "Not set";
  }
  if (value.length < 12) {
    return "****" + "*".repeat(Math.min(value.length, 4)); // Fixed length, no info leak
  }
  return "****" + value.slice(-4); // Show last 4 chars only for longer secrets
}

// Simple configuration display for Vite context
function displayFrontendConfig(): void {
  const env = loadEnvFile();
  
  console.log("─".repeat(50));
  console.log("🌐 ENEO Frontend Configuration");
  console.log("─".repeat(50));
  
  // Essential info only - with secret masking
  console.log(`Backend: ${env.INTRIC_BACKEND_URL || 'Not configured'}`);
  console.log(`JWT Secret: ${maskSecret(env.JWT_SECRET)}`);
  console.log(`System API Key: ${maskSecret(env.INTRIC_SYS_API_KEY)}`);
  
  // Auth providers (with masked secrets)
  const mobilityGuardConfigured = Boolean(env.MOBILITY_GUARD_AUTH && env.MOBILITYGUARD_CLIENT_ID);
  const zitadelConfigured = Boolean(env.ZITADEL_INSTANCE_URL && env.ZITADEL_PROJECT_CLIENT_ID);
  const authCount = [mobilityGuardConfigured, zitadelConfigured].filter(Boolean).length;
  console.log(`Auth: ${authCount}/2 configured`);
  
  if (mobilityGuardConfigured) {
    console.log(`   ✅ MobilityGuard: ${maskSecret(env.MOBILITYGUARD_CLIENT_ID)}`);
  }
  if (zitadelConfigured) {
    console.log(`   ✅ Zitadel: ${maskSecret(env.ZITADEL_PROJECT_CLIENT_ID)}`);
  }
  
  // UI Features (simple check)
  const uiFeatures = [env.SHOW_TEMPLATES, env.SHOW_WEB_SEARCH, env.SHOW_HELP_CENTER];
  const uiEnabled = uiFeatures.filter(f => f?.toLowerCase() === 'true').length;
  console.log(`Features: ${uiEnabled}/3 enabled`);
  
  if (uiEnabled > 0) {
    const enabledList = [];
    if (env.SHOW_TEMPLATES?.toLowerCase() === 'true') enabledList.push('templates');
    if (env.SHOW_WEB_SEARCH?.toLowerCase() === 'true') enabledList.push('web_search');
    if (env.SHOW_HELP_CENTER?.toLowerCase() === 'true') enabledList.push('help_center');
    console.log(`   ✅ Enabled: ${enabledList.join(', ')}`);
  }
  
  // Basic validation
  const hasRequiredConfig = Boolean(env.INTRIC_BACKEND_URL && env.JWT_SECRET);
  if (hasRequiredConfig) {
    console.log("✅ Configuration OK");
  } else {
    const missing = [];
    if (!env.INTRIC_BACKEND_URL) missing.push('INTRIC_BACKEND_URL');
    if (!env.JWT_SECRET) missing.push('JWT_SECRET');
    console.log(`⚠️ Missing required: ${missing.join(', ')}`);
  }
  
  console.log("─".repeat(50));
}

// Frontend configuration display plugin
function frontendConfigPlugin(): PluginOption {
  return {
    name: 'frontend-config-display',
    configureServer() {
      try {
        displayFrontendConfig();
      } catch (error) {
        console.warn('⚠️ Could not display frontend configuration:', (error as Error).message);
      }
    }
  };
}

export default defineConfig({
  plugins: [
    // visualizer({
    //   emitFile: true,
    //   filename: "stats.html"
    // }),
    frontendConfigPlugin() as PluginOption,
    tailwindcss() as PluginOption,
    intricIcons() as PluginOption,
    sveltekit() as PluginOption
  ],
  test: {
    include: ["src/**/*.{test,spec}.{js,ts}"]
  },
  server: {
    host: process.env.HOST ? "0.0.0.0" : undefined,
    port: 3000,
    strictPort: true
  },
  define: {
    __FRONTEND_VERSION__: JSON.stringify(pkg.version),
    __IS_PREVIEW__: process.env.CF_PAGES_BRANCH ? true : process.env.VERCEL_ENV === "preview",
    __GIT_BRANCH__: process.env.CF_PAGES_BRANCH
      ? `"${process.env.CF_PAGES_BRANCH}"`
      : `"${process.env.VERCEL_GIT_COMMIT_REF}"`,
    __GIT_COMMIT_SHA__: process.env.CF_PAGES_COMMIT_SHA
      ? `"${process.env.CF_PAGES_COMMIT_SHA}"`
      : `"${process.env.VERCEL_GIT_COMMIT_SHA}"`
  }
});
