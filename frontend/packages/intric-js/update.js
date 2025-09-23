#!/usr/bin/env node
/**
 * Updater script to download latest openapi.json from staging and update types and client version
 */
import fs from "fs";
import { exec, spawn } from "node:child_process";

const localUrl = "http://localhost:8123";
const remoteUrl = process.env.INTRIC_BACKEND_URL || "http://localhost:8123";

/** @param {string} baseUrl */
async function updateClient(baseUrl) {
  const url = `${baseUrl}/openapi.json`;
  const version = await fetch(url)
    .then((res) => res.json())
    .then((json) => json.info.version);
  if (version) {
    // Update actual client.js file
    const clientFile = "./src/client/client.js";
    const client = String(fs.readFileSync(clientFile));

    // looks like this:
    // const version = "...";
    const regex = /(?<=const version = ")(.*)(?=";)/;
    const updatedClient = client.replace(regex, version);

    fs.writeFileSync(clientFile, updatedClient);

    console.log(`Updated client/client.js with current schema version ${version}`);
  } else {
    console.log("Could not update client/client.js version");
  }
}

/** @param {string} baseUrl */
function updateSchema(baseUrl) {
  return new Promise((resolve, reject) => {
    exec(
      `pnpm exec openapi-typescript ${baseUrl}/openapi.json -o src/types/schema.d.ts`,
      (err, stdout, stderr) => {
        if (err) {
          console.log(err);
          reject(err);
          return;
        }
        console.log(stdout);
        console.error(stderr);
        resolve(true);
      }
    );
  });
}

function runFormatter() {
  return new Promise((resolve, reject) => {
    const formatProcess = spawn("pnpm", ["run", "format"], { stdio: "inherit" });

    formatProcess.on("close", (code) => {
      if (code === 0) {
        resolve(true);
      } else {
        reject(new Error(`Format process exited with code ${code}`));
      }
    });
  });
}

async function main() {
  try {
    // Check for --local flag in command line arguments
    const useLocal = process.argv.some((value) => value === "--local");
    const url = useLocal ? localUrl : remoteUrl;

    console.log(`Updating from ${url}`);

    // Update client and schema
    await updateClient(url);
    await updateSchema(url);

    // Run formatter
    await runFormatter();

    console.log("Update completed successfully");
  } catch (error) {
    console.error("Update failed:", error);
    process.exit(1);
  }
}

// Run the main function
main();
