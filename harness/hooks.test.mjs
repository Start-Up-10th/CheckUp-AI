import assert from 'node:assert/strict';
import test from 'node:test';
import { inspectPreTool, postToolNotice } from './hooks.mjs';

test('blocks credential-shaped content in source files', () => {
  const result = inspectPreTool({
    tool_name: 'Write',
    tool_input: { file_path: 'server/src/config.ts', content: 'const token = "ghp_123456789012345678901234567890";' }
  });
  assert.equal(result.blocked, true);
});

test('allows environment files for local secrets', () => {
  const result = inspectPreTool({
    tool_name: 'Write',
    tool_input: { file_path: '.env.local', content: 'DATAGSM_CLIENT_SECRET="a-real-local-secret"' }
  });
  assert.equal(result.blocked, false);
});

test('allows placeholders in example configuration', () => {
  const result = inspectPreTool({
    tool_name: 'Write',
    tool_input: { file_path: 'infra/.env.example', content: 'DATAGSM_CLIENT_SECRET="your-secret"' }
  });
  assert.equal(result.blocked, false);
});

test('blocks destructive git and Docker commands', () => {
  for (const command of ['git reset --hard HEAD', 'docker compose down -v', 'docker system prune -af']) {
    const result = inspectPreTool({ tool_name: 'Bash', tool_input: { command } });
    assert.equal(result.blocked, true, command);
  }
});

test('allows ordinary development commands', () => {
  const result = inspectPreTool({ tool_name: 'Bash', tool_input: { command: 'docker compose config --quiet' } });
  assert.equal(result.blocked, false);
});

test('asks for synchronization and validation after skill changes', () => {
  const notice = postToolNotice({ tool_name: 'Edit', tool_input: { file_path: '.agents/skills/dorm-verify/SKILL.md' } });
  assert.match(notice, /npm run harness:sync/);
  assert.match(notice, /npm run harness:check/);
});

test('asks for validation after specification changes', () => {
  const notice = postToolNotice({ tool_name: 'Write', tool_input: { file_path: 'docs/spec/face.md' } });
  assert.match(notice, /npm run harness:check/);
});

test('does not announce unrelated source edits', () => {
  assert.equal(postToolNotice({ tool_name: 'Edit', tool_input: { file_path: 'server/src/App.java' } }), null);
});
