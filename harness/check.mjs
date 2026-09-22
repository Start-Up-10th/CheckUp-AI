import { existsSync, lstatSync, readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const ignored = new Set(['.git', 'node_modules', '.next', '.venv', '.gradle', 'dist', 'build', 'target', 'coverage', '.local', '__pycache__', 'test-results', 'playwright-report']);
const normalize = text => text.replace(/^\uFEFF/, '').replace(/\r\n/g, '\n');
const read = filename => normalize(readFileSync(filename, 'utf8'));

// Keep even caller-supplied paths and symlinks within the chosen repository.
export function inside(root, relative) {
  if (typeof relative !== 'string' || !relative || path.isAbsolute(relative) || /^[A-Za-z]:/.test(relative)) {
    throw new Error('Expected a repository-relative path');
  }
  const target = path.resolve(root, relative);
  const rel = path.relative(root, target);
  if (rel === '..' || rel.startsWith(`..${path.sep}`) || path.isAbsolute(rel)) {
    throw new Error(`Path escapes repository: ${relative}`);
  }
  let cursor = root;
  for (const part of rel.split(path.sep).filter(Boolean)) {
    cursor = path.join(cursor, part);
    if (lstatSync(cursor, { throwIfNoEntry: false })?.isSymbolicLink()) {
      throw new Error(`Symlink is not supported by the harness: ${relative}`);
    }
  }
  return target;
}

function walk(root, directory = root) {
  const files = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    if (ignored.has(entry.name) || entry.isSymbolicLink()) continue;
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...walk(root, absolute));
    else if (entry.isFile()) files.push(path.relative(root, absolute).split(path.sep).join('/'));
  }
  return files;
}

function isNonEmptyFile(filename) {
  return existsSync(filename) && lstatSync(filename).isFile() && lstatSync(filename).size > 0;
}

export function skillNames(root, relative = '.agents/skills') {
  const directory = inside(root, relative);
  if (!existsSync(directory)) throw new Error(`Missing skill directory: ${relative}`);
  return readdirSync(directory, { withFileTypes: true }).map(entry => {
    if (entry.isSymbolicLink() || !entry.isDirectory() || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(entry.name) || entry.name.length >= 64) {
      throw new Error(`Invalid skill directory: ${relative}/${entry.name}`);
    }
    return entry.name;
  }).sort();
}

export function validate(root = ROOT) {
  root = path.resolve(root);
  const errors = [];
  const report = { requirements: 0, scenarios: 0, skills: 0, markdownFiles: 0, verifiedScenarios: 0 };
  const fail = message => errors.push(message);
  const attempt = fn => { try { return fn(); } catch (error) { fail(error.message); return undefined; } };
  const json = relative => attempt(() => JSON.parse(read(inside(root, relative))));
  const manifest = json('harness/manifest.json');
  if (!manifest || manifest.schemaVersion !== 1 || !Array.isArray(manifest.requiredFiles) || !manifest.requiredFiles.length || !Array.isArray(manifest.skills) || !manifest.skills.length || !Array.isArray(manifest.scopes) || !manifest.scopes.length) {
    fail('Invalid or empty harness manifest');
    return { errors, ...report };
  }
  for (const relative of manifest.requiredFiles) {
    attempt(() => { if (!isNonEmptyFile(inside(root, relative))) fail(`Missing or empty required file: ${relative}`); });
  }
  const files = attempt(() => walk(root)) ?? [];
  const definitions = new Map();
  const knownSources = new Set((attempt(() => read(inside(root, 'docs/sources/README.md'))) ?? '').match(/\bSRC-[A-Z][A-Z-]+\b/g) ?? []);
  for (const relative of files.filter(file => file.startsWith('docs/spec/') && file.endsWith('.md'))) {
    const content = read(inside(root, relative));
    const headers = [...content.matchAll(/^### (REQ-[A-Z]+-\d{3})\s+—\s+(.+)$/gm)];
    for (let i = 0; i < headers.length; i++) {
      const [heading, id] = headers[i];
      if (definitions.has(id)) fail(`Duplicate requirement: ${id}`);
      definitions.set(id, relative);
      const body = content.slice(headers[i].index + heading.length, headers[i + 1]?.index ?? content.length);
      const sources = body.match(/\bSRC-[A-Z][A-Z-]+\b/g) ?? [];
      if (!sources.length) fail(`No source provenance for ${id}`);
      for (const source of sources) if (!knownSources.has(source)) fail(`Unknown source ${source} in ${id}`);
    }
  }
  report.requirements = definitions.size;
  if (!definitions.size) fail('No requirement definitions found');

  const catalog = json('tests/acceptance/scenarios.json');
  if (catalog?.schemaVersion !== 1 || !Array.isArray(catalog?.scenarios) || !catalog.scenarios.length) {
    fail('Invalid or empty acceptance catalog');
  } else {
    const covered = new Set();
    const ids = new Set();
    for (const scenario of catalog.scenarios) {
      if (!scenario || typeof scenario !== 'object') { fail('Invalid acceptance scenario'); continue; }
      const id = scenario.id;
      if (typeof id !== 'string' || !/^ACC-[A-Z]+-\d{3}$/.test(id) || ids.has(id)) fail(`Invalid or duplicate scenario ID: ${id}`);
      ids.add(id);
      for (const field of ['title', 'given', 'when']) {
        if (typeof scenario[field] !== 'string' || !scenario[field].trim()) fail(`Missing ${field} in ${id}`);
      }
      for (const field of ['requirements', 'then']) {
        if (!Array.isArray(scenario[field]) || !scenario[field].length || scenario[field].some(value => typeof value !== 'string' || !value.trim())) fail(`Invalid ${field} in ${id}`);
      }
      for (const req of Array.isArray(scenario.requirements) ? scenario.requirements : []) {
        if (!definitions.has(req)) fail(`Unknown requirement ${req} in ${id}`);
        covered.add(req);
      }
      if (!['specified', 'implemented', 'verified'].includes(scenario.status)) fail(`Invalid status in ${id}`);
      for (const field of ['implementation', 'evidence']) {
        if (!Array.isArray(scenario[field])) { fail(`Missing ${field} array in ${id}`); continue; }
        for (const relative of scenario[field]) attempt(() => {
          if (!isNonEmptyFile(inside(root, relative))) fail(`Missing ${field} file in ${id}: ${relative}`);
        });
      }
      if (['implemented', 'verified'].includes(scenario.status) && !scenario.implementation?.length) fail(`No implementation evidence for ${id}`);
      if (scenario.status === 'verified') {
        report.verifiedScenarios++;
        if (!scenario.evidence?.length) fail(`No verification evidence for ${id}`);
      }
    }
    for (const id of definitions.keys()) if (!covered.has(id)) fail(`Requirement has no acceptance scenario: ${id}`);
    report.scenarios = catalog.scenarios.length;
  }

  const markdownFiles = files.filter(file => file.endsWith('.md'));
  report.markdownFiles = markdownFiles.length;
  for (const relative of markdownFiles) {
    const content = read(inside(root, relative));
    const prose = content.replace(/^```[^\n]*\n[\s\S]*?^```\s*$/gm, '');
    for (const match of prose.matchAll(/!?\[[^\]\n]*\]\((<[^>]+>|[^)\s]+)(?:\s+"[^"]*")?\)/g)) {
      let link = match[1].replace(/^<|>$/g, '');
      if (/^(?:https?:|mailto:|#)/i.test(link)) continue;
      attempt(() => {
        link = decodeURIComponent(link.split('#')[0].split('?')[0]);
        if (!link) return;
        if (/^[A-Za-z]:|^[/\\]/.test(link)) throw new Error(`Nonportable link in ${relative}: ${link}`);
        const destination = inside(root, path.join(path.dirname(relative), link));
        if (!existsSync(destination)) fail(`Broken local link in ${relative}: ${link}`);
      });
    }
  }

  for (const scope of ['', ...manifest.scopes]) {
    attempt(() => {
      const filename = path.join(scope, 'CLAUDE.md');
      if (!/^@AGENTS\.md\s*$/m.test(read(inside(root, filename)))) fail(`Missing @AGENTS.md import: ${filename}`);
      const rootInstructions = read(inside(root, 'AGENTS.md'));
      const scopedInstructions = scope ? read(inside(root, path.join(scope, 'AGENTS.md'))) : '';
      if (Buffer.byteLength(rootInstructions + scopedInstructions, 'utf8') > 32768) fail(`Instruction chain exceeds 32 KiB: ${scope || 'root'}`);
    });
  }

  const originals = attempt(() => skillNames(root)) ?? [];
  const mirrors = attempt(() => skillNames(root, '.claude/skills')) ?? [];
  for (const name of manifest.skills) if (!originals.includes(name)) fail(`Missing required skill: ${name}`);
  for (const name of mirrors) if (!originals.includes(name)) fail(`Stale Claude skill: ${name}`);
  for (const name of originals) {
    attempt(() => {
      const content = read(inside(root, `.agents/skills/${name}/SKILL.md`));
      const frontmatter = content.match(/^---\n([\s\S]*?)\n---\n/);
      if (!frontmatter) fail(`Missing skill frontmatter: ${name}`);
      else {
        const actualName = frontmatter[1].match(/^name:\s*([a-z0-9-]+)\s*$/m)?.[1];
        const description = frontmatter[1].match(/^description:\s*(\S[^\n]*)$/m)?.[1];
        if (actualName !== name || !description) fail(`Invalid skill name/description: ${name}`);
      }
      if (!mirrors.includes(name)) fail(`Missing Claude skill mirror: ${name}`);
      else if (content !== read(inside(root, `.claude/skills/${name}/SKILL.md`))) fail(`Skill mirror differs: ${name}; run npm run harness:sync`);
    });
  }
  report.skills = originals.length;
  const settings = json('.claude/settings.json');
  if (!settings?.permissions || !Array.isArray(settings.permissions.allow)) fail('Invalid Claude project settings');
  if (!settings?.hooks?.PreToolUse?.length || !settings?.hooks?.PostToolUse?.length) fail('Claude hooks are not configured');
  const codexHooks = json('.codex/hooks.json');
  if (!codexHooks?.hooks?.PreToolUse?.length || !codexHooks?.hooks?.PostToolUse?.length) fail('Codex hooks are not configured');
  const packageFile = json('package.json');
  if (!packageFile?.private || !packageFile.scripts?.['harness:check'] || !packageFile.scripts?.['harness:sync']) fail('Missing harness package scripts');
  return { errors, ...report };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const result = validate();
  if (result.errors.length) {
    for (const error of result.errors) console.error(`FAIL ${error}`);
    process.exitCode = 1;
  } else {
    console.log(`PASS harness: ${result.requirements} requirements, ${result.scenarios} acceptance scenarios, ${result.skills} shared skills, ${result.markdownFiles} Markdown files`);
    console.log(`Product verification: ${result.verifiedScenarios}/${result.scenarios} scenarios marked verified. Document checks are not application tests.`);
  }
}
