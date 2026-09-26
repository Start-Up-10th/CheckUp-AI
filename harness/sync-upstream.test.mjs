import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const manifest = JSON.parse(readFileSync(new URL('./upstream-manifest.json', import.meta.url), 'utf8'));

test('integrated hooks are preserved and never copied from ALL_harness', () => {
  assert.ok(manifest.preservePaths.includes('harness/hooks.mjs'));
  assert.ok(manifest.preservePaths.includes('harness/hooks.test.mjs'));
  assert.equal(manifest.paths.includes('harness/hooks.mjs'), false);
  assert.equal(manifest.paths.includes('harness/hooks.test.mjs'), false);
});

test('upstream sync never deletes files outside its allowlist', () => {
  assert.equal(manifest.paths.some(path => path === 'harness'), false);
});
