#!/usr/bin/env node
// Derives the documentation versions to publish from git refs, so nothing has to
// be edited at release time:
//
//   stable   the release/vX.Y branch tip (or the tag itself) of the highest final
//            vX.Y.Z tag — hotfixes to docs on the release branch republish stable
//   archive  the next DOCS_ARCHIVED_LINES older release lines, served under /vX.Y
//   dev      the working tree (develop on deploys, the PR head on pull requests)
//
// Release candidates (v2.2.0-rc.1) never count as final, so stable does not flip
// until the real tag exists. A release line is skipped when its ref has no
// docs-site content. When no final tag with docs exists, dev is served at the root.
import { execFileSync } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const APP_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
export const WORKTREE_REF = 'WORKTREE'
export const REPO_CONTENT_DIR = 'frontend/apps/docs-site/src/content'

const FINAL_TAG = /^v(\d+)\.(\d+)\.(\d+)$/

// git resolves tree paths relative to the cwd, so every call runs from the repo root.
export const REPO_ROOT = execFileSync('git', ['rev-parse', '--show-toplevel'], { cwd: APP_DIR, encoding: 'utf8' }).trim()

export function git(...args) {
  return execFileSync('git', args, { cwd: REPO_ROOT, encoding: 'utf8' }).trim()
}

function refExists(ref) {
  try {
    execFileSync('git', ['rev-parse', '--verify', '--quiet', `${ref}^{commit}`], {
      cwd: REPO_ROOT,
      stdio: 'ignore',
    })
    return true
  } catch {
    return false
  }
}

function hasDocsContent(ref) {
  try {
    return git('ls-tree', '-d', ref, '--', REPO_CONTENT_DIR).length > 0
  } catch {
    return false
  }
}

function parseTag(name) {
  const match = FINAL_TAG.exec(name)
  if (!match) return null
  const [major, minor, patch] = match.slice(1).map(Number)
  return { name, major, minor, patch }
}

function newestFirst(a, b) {
  return b.major - a.major || b.minor - a.minor || b.patch - a.patch
}

function releaseLines() {
  const tags = git('tag', '-l', 'v*').split('\n').map(parseTag).filter(Boolean).sort(newestFirst)
  const lines = new Map()
  for (const tag of tags) {
    const line = `v${tag.major}.${tag.minor}`
    if (!lines.has(line)) lines.set(line, tag)
  }
  return [...lines].map(([line, tag]) => {
    const branch = [`origin/release/${line}`, `release/${line}`].find(refExists)
    return { line, tag: tag.name, ref: branch ?? tag.name }
  })
}

export function resolveVersions({ archivedLines = Number(process.env.DOCS_ARCHIVED_LINES ?? 3), only } = {}) {
  const dev = {
    id: 'dev',
    label: 'dev',
    kind: 'dev',
    ref: WORKTREE_REF,
    gitRef: process.env.DOCS_DEV_GIT_REF || 'develop',
    basePath: '/dev',
  }
  if (only === 'dev') return [{ ...dev, basePath: '' }]

  const versions = releaseLines()
    .filter((line) => hasDocsContent(line.ref))
    .slice(0, archivedLines + 1)
    .map((line, index) => ({
      id: line.line,
      label: line.line,
      kind: index === 0 ? 'stable' : 'archive',
      ref: line.ref,
      gitRef: line.ref.replace(/^origin\//, ''),
      tag: line.tag,
      basePath: index === 0 ? '' : `/${line.line}`,
    }))

  if (versions.length === 0) dev.basePath = ''
  versions.push(dev)
  return versions
}

export function parseArgs(argv) {
  const args = { only: undefined, out: undefined, archivedLines: undefined, strict: false }
  for (let i = 0; i < argv.length; i++) {
    switch (argv[i]) {
      case '--only':
        args.only = argv[++i]
        break
      case '--out':
        args.out = argv[++i]
        break
      case '--archived':
        args.archivedLines = Number(argv[++i])
        break
      case '--strict':
        args.strict = true
        break
      default:
        throw new Error(`Unknown argument: ${argv[i]}`)
    }
  }
  return args
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = parseArgs(process.argv.slice(2))
  const versions = resolveVersions(args)
  const json = JSON.stringify({ versions }, null, 2)
  if (args.out) writeFileSync(args.out, json + '\n')
  else console.log(json)
}
