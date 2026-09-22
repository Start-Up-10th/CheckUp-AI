import test from 'node:test';
import assert from 'node:assert/strict';
import { cpSync, existsSync, lstatSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ROOT, inside, validate } from './check.mjs';
import { syncSkills } from './sync-skills.mjs';

// Mutations use an isolated temporary copy, never the working repository.
function fixture(t) {
  const temp = mkdtempSync(path.join(os.tmpdir(), 'dorm-harness-test-'));
  const repo = path.join(temp, 'repo');
  const inputs = ['README.md', 'AGENTS.md', 'CLAUDE.md', 'package.json', '.gitignore', '.codex', '.claude', '.agents', 'docs', 'contracts', 'web', 'server', 'ai', 'infra', 'tests', 'harness', '.github'];
  mkdirSync(repo);
  const excluded = new Set(['node_modules', '.next', '.venv', '.git', 'target', 'build', 'dist', 'coverage', '.local', 'datasets', 'models', 'backups', 'auth.json', 'settings.local.json', 'sessions', 'log']);
  const safeInput = source => {
    const name = path.basename(source);
    return !excluded.has(name) && !lstatSync(source).isSymbolicLink()
      && !(name.startsWith('.env') && name !== '.env.example')
      && !/\.(?:pem|key|log|onnx|pt|pth)$/.test(name);
  };
  for (const item of inputs) cpSync(path.join(ROOT, item), path.join(repo, item), { recursive: true, filter: safeInput });
  t.after(() => {
    const resolved = path.resolve(temp);
    assert.equal(path.dirname(resolved), path.resolve(os.tmpdir()));
    assert.ok(path.basename(resolved).startsWith('dorm-harness-test-'));
    rmSync(resolved, { recursive: true, force: true });
  });
  return repo;
}

function editJson(repo, relative, edit) {
  const filename = path.join(repo, relative);
  const data = JSON.parse(readFileSync(filename, 'utf8'));
  edit(data);
  writeFileSync(filename, JSON.stringify(data, null, 2) + '\n');
}

test('actual repository has a consistent harness', () => {
  const result = validate();
  assert.deepEqual(result.errors, []);
  assert.ok(result.requirements > 0);
  assert.ok(result.scenarios >= result.requirements);
});

test('missing scenario is rejected', t => {
  const repo = fixture(t);
  editJson(repo, 'tests/acceptance/scenarios.json', data => data.scenarios.shift());
  assert.ok(validate(repo).errors.some(error => error.includes('has no acceptance scenario')));
});

test('undefined requirements are rejected', t => {
  const repo = fixture(t);
  editJson(repo, 'tests/acceptance/scenarios.json', data => data.scenarios[0].requirements.push('REQ-UNKNOWN-999'));
  assert.ok(validate(repo).errors.some(error => error.includes('Unknown requirement')));
});

test('verified cannot be asserted without implementation and test evidence', t => {
  const repo = fixture(t);
  editJson(repo, 'tests/acceptance/scenarios.json', data => { data.scenarios[0].status = 'verified'; });
  const errors = validate(repo).errors;
  assert.ok(errors.some(error => error.includes('No implementation evidence')));
  assert.ok(errors.some(error => error.includes('No verification evidence')));
});

test('missing evidence file is rejected', t => {
  const repo = fixture(t);
  editJson(repo, 'tests/acceptance/scenarios.json', data => { data.scenarios[0].evidence = ['tests/does-not-exist.test.ts']; });
  assert.ok(validate(repo).errors.some(error => error.includes('Missing evidence file')));
});

test('broken local Markdown links are rejected', t => {
  const repo = fixture(t);
  writeFileSync(path.join(repo, 'docs', 'bad-link.md'), '[missing](not-a-real-file.md)\n');
  assert.ok(validate(repo).errors.some(error => error.includes('Broken local link')));
});

test('duplicate requirement definitions are rejected', t => {
  const repo = fixture(t);
  writeFileSync(path.join(repo, 'docs', 'spec', 'duplicate.md'), '### REQ-SCOPE-001 — duplicate\n\nSRC-INTERVIEW\n');
  assert.ok(validate(repo).errors.some(error => error.includes('Duplicate requirement')));
});

test('skill drift is rejected and mechanical synchronization repairs it', t => {
  const repo = fixture(t);
  const mirror = path.join(repo, '.claude', 'skills', 'dorm-verify', 'SKILL.md');
  writeFileSync(mirror, readFileSync(mirror, 'utf8') + '\nChanged only in Claude.\n');
  assert.ok(validate(repo).errors.some(error => error.includes('Skill mirror differs')));
  assert.equal(syncSkills(repo).changed, 1);
  assert.deepEqual(validate(repo).errors, []);
  assert.equal(syncSkills(repo).changed, 0);
});

test('missing Claude import is rejected', t => {
  const repo = fixture(t);
  writeFileSync(path.join(repo, 'CLAUDE.md'), '# No shared instructions\n');
  assert.ok(validate(repo).errors.some(error => error.includes('Missing @AGENTS.md')));
});

test('stale skill is reported without deletion', t => {
  const repo = fixture(t);
  const stale = path.join(repo, '.claude', 'skills', 'obsolete');
  mkdirSync(stale);
  writeFileSync(path.join(stale, 'SKILL.md'), '---\nname: obsolete\ndescription: Stale skill\n---\n');
  assert.throws(() => syncSkills(repo), /Stale Claude skills/);
  assert.ok(existsSync(stale));
});

test('paths cannot escape repository or use host absolute paths', () => {
  assert.throws(() => inside(ROOT, '../outside'), /escapes repository/);
  assert.throws(() => inside(ROOT, 'C:\\outside'), /relative path/);
  assert.throws(() => inside(ROOT, '/outside'), /relative path/);
  assert.equal(inside(ROOT, 'docs/spec/index.md'), path.join(ROOT, 'docs', 'spec', 'index.md'));
});

test('corrupted JSON is reported as failure', t => {
  const repo = fixture(t);
  writeFileSync(path.join(repo, 'tests', 'acceptance', 'scenarios.json'), '{invalid');
  assert.ok(validate(repo).errors.length > 0);
});
