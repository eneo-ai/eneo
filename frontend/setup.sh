#!/bin/sh

echo "Eneo Frontend\nRunning first setup..."
echo "\nRunning bun install..."
bun install

echo "\nBuilding dependencies..."

if [ -n "${GITHUB}" ]; then
  echo "Setup for Github actions..."
  bun run --filter @intric/ui build
  echo "Github setup done."
else
  echo "Build all"
  bun run --filter @intric/ui build
  echo "\nDone.\n\nStart developing by running 'bun run dev'"
fi
