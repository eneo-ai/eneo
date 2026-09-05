#!/usr/bin/env node
// Builds every documentation version into one static site directory:
//
//   site/           stable
//   site/vX.Y/      archived release lines
//   site/dev/       development docs
//
// Each version is built with the site code of the current working tree and the
// content (src/content + public) of that version's git ref, so a version switcher,
// banner or theme change applies to all versions without touching release branches.
// The working tree's own content is restored after every ref build, also on failure.
//
// Usage: node scripts/build-versions.mjs [--only dev] [--archived N] [--strict]
//   --only dev   build just the working tree at the root (pull-request checks, local preview)
//   --strict     fail when an archived version fails to build (default: warn and skip)
import { execFileSync, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { APP_DIR, REPO_CONTENT_DIR, REPO_ROOT, WORKTREE_REF, parseArgs, resolveVersions } from './resolve-versions.mjs'

const REPO_PUBLIC_DIR = 'frontend/apps/docs-site/public'
const CONTENT_DIR = path.join(APP_DIR, 'src/content')
const PUBLIC_DIR = path.join(APP_DIR, 'public')
const OUT_DIR = path.join(APP_DIR, 'out')
const NEXT_DIR = path.join(APP_DIR, '.next')
const SITE_DIR = process.env.DOCS_SITE_DIR ? path.resolve(process.env.DOCS_SITE_DIR) : path.join(APP_DIR, 'site')
const BUN = process.env.BUN_BIN || 'bun'

const restorers = []

function restoreAll() {
  while (restorers.length) restorers.pop()()
}

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    restoreAll()
    process.exit(130)
  })
}

function swapIn(target, replacement) {
  const backup = `${target}.__worktree`
  fs.rmSync(backup, { recursive: true, force: true })
  fs.renameSync(target, backup)
  fs.cpSync(replacement, target, { recursive: true })
  restorers.push(() => {
    fs.rmSync(target, { recursive: true, force: true })
    fs.renameSync(backup, target)
  })
}

function withContentFrom(ref, fn) {
  if (ref === WORKTREE_REF) return fn()
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'eneo-docs-'))
  const archive = path.join(tmp, 'content.tar')
  try {
    execFileSync('git', ['archive', '--format=tar', '-o', archive, ref, '--', REPO_CONTENT_DIR, REPO_PUBLIC_DIR], {
      cwd: REPO_ROOT,
      stdio: 'inherit',
    })
    execFileSync('tar', ['-xf', archive, '-C', tmp], { stdio: 'inherit' })
    swapIn(CONTENT_DIR, path.join(tmp, REPO_CONTENT_DIR))
    swapIn(PUBLIC_DIR, path.join(tmp, REPO_PUBLIC_DIR))
    return fn()
  } finally {
    restoreAll()
    fs.rmSync(tmp, { recursive: true, force: true })
  }
}

function publicManifest(versions) {
  return versions.map(({ id, label, kind, basePath, gitRef, tag }) => ({ id, label, kind, basePath, gitRef, tag }))
}

function buildVersion(version, versions) {
  const env = {
    ...process.env,
    NEXT_PUBLIC_DOCS_VERSION: version.id,
    NEXT_PUBLIC_DOCS_VERSIONS: JSON.stringify(publicManifest(versions)),
    NEXT_PUBLIC_DOCS_REF: version.gitRef,
  }
  // next.config.ts only accepts an unset or "/"-prefixed basePath
  if (version.basePath) env.PAGES_BASE_PATH = version.basePath
  else delete env.PAGES_BASE_PATH

  withContentFrom(version.ref, () => {
    fs.rmSync(NEXT_DIR, { recursive: true, force: true })
    fs.rmSync(OUT_DIR, { recursive: true, force: true })
    const result = spawnSync(BUN, ['run', 'build'], { cwd: APP_DIR, env, stdio: 'inherit' })
    if (result.status !== 0) throw new Error(`build exited with status ${result.status}`)
    const destination = path.join(SITE_DIR, version.basePath.replace(/^\//, ''))
    fs.mkdirSync(destination, { recursive: true })
    fs.cpSync(OUT_DIR, destination, { recursive: true })
  })
}

function writeStepSummary(rows) {
  const lines = [
    '### Documentation versions',
    '',
    '| Version | Kind | Ref | Path | Status |',
    '| --- | --- | --- | --- | --- |',
    ...rows.map((r) => `| ${r.label} | ${r.kind} | \`${r.ref}\` | \`${r.basePath || '/'}\` | ${r.status} |`),
  ]
  const summary = lines.join('\n') + '\n'
  if (process.env.GITHUB_STEP_SUMMARY) fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, summary)
  console.log('\n' + summary)
}

function main() {
  const args = parseArgs(process.argv.slice(2))
  const versions = resolveVersions(args)
  fs.rmSync(SITE_DIR, { recursive: true, force: true })
  fs.mkdirSync(SITE_DIR, { recursive: true })

  const rows = []
  for (const version of versions) {
    console.log(`\n▶ Building ${version.label} (${version.kind}) from ${version.ref} into ${version.basePath || '/'}`)
    try {
      buildVersion(version, versions)
      rows.push({ ...version, status: 'built' })
    } catch (error) {
      if (version.kind === 'archive' && !args.strict) {
        console.warn(`⚠ Skipping archived version ${version.label}: ${error.message}`)
        rows.push({ ...version, status: `skipped (${error.message})` })
        continue
      }
      rows.push({ ...version, status: 'failed' })
      writeStepSummary(rows)
      throw error
    }
  }

  const cname = path.join(PUBLIC_DIR, 'CNAME')
  if (fs.existsSync(cname)) fs.copyFileSync(cname, path.join(SITE_DIR, 'CNAME'))
  fs.writeFileSync(
    path.join(SITE_DIR, 'versions.json'),
    JSON.stringify({ generatedAt: new Date().toISOString(), versions: rows }, null, 2) + '\n',
  )
  writeStepSummary(rows)
}

try {
  main()
} finally {
  restoreAll()
}
