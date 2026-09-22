import { basename } from 'node:path';

const SHELL_TOOLS = new Set(['Bash', 'bash', 'Shell', 'shell', 'exec_command', 'run_command']);
const WRITE_TOOLS = new Set(['Edit', 'Write', 'write_file', 'write', 'apply_patch']);

const SECRET_PATTERNS = [
  { pattern: /\bAKIA[0-9A-Z]{16}\b/, label: 'AWS access key' },
  { pattern: /\b(?:ghp|gho|ghs|ghr)_[A-Za-z0-9]{20,}\b/, label: 'GitHub token' },
  { pattern: /\bgithub_pat_[A-Za-z0-9_]{20,}\b/, label: 'GitHub token' },
  { pattern: /\bxox[baprs]-[A-Za-z0-9-]+\b/, label: 'Slack token' },
  { pattern: /\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b/, label: 'API key' },
  { pattern: /-----BEGIN[\s\S]{0,80}PRIVATE KEY-----/, label: 'private key' }
];

const SECRET_ASSIGNMENT = /\b(?:client[_-]?secret|oauth[_-]?secret|access[_-]?token|refresh[_-]?token|private[_-]?key|database[_-]?password)\b\s*[:=]\s*["'`]([^"'`\r\n]{8,})["'`]/i;

const DANGEROUS_COMMANDS = [
  { pattern: /\bgit\s+reset\s+--hard\b/i, label: 'git reset --hard' },
  { pattern: /\bgit\s+clean\s+-[^\r\n]*f/i, label: 'git clean with force' },
  { pattern: /\bgit\s+(?:checkout|restore)\s+--?\s*(?:\.|$)/i, label: 'discarding the working tree' },
  { pattern: /\brm\s+-rf\s+(?:\/|\.\/?|\*|\\)/i, label: 'recursive root/workspace deletion' },
  { pattern: /\bRemove-Item\b[^\r\n]*(?:-Recurse|-r)\b/i, label: 'PowerShell recursive deletion' },
  { pattern: /\bdocker\s+(?:system|volume)\s+prune\b/i, label: 'Docker prune' },
  { pattern: /\bdocker\s+compose\b[^\r\n]*\bdown\b[^\r\n]*(?:-v|--volumes)\b/i, label: 'Docker volume deletion' },
  { pattern: /\b(?:dropdb|DROP\s+DATABASE|FLUSHALL|FLUSHDB)\b/i, label: 'database-wide deletion' }
];

const PLACEHOLDER = /^(?:\$\{[^}]+\}|<[^>]+>|your[_-]?(?:secret|token|password|key)|change[_-]?me|replace[_-]?me|placeholder|dummy|example|redacted|test(?:[_-].*)?)$/i;

function toolInput(payload) {
  return payload?.tool_input ?? payload?.toolInput ?? {};
}

function toolName(payload) {
  return String(payload?.tool_name ?? payload?.toolName ?? '');
}

function firstString(values) {
  return values.find(value => typeof value === 'string' && value.length > 0) ?? '';
}

function commandFrom(payload) {
  const input = toolInput(payload);
  return firstString([input.command, input.cmd, input.script, input.text]);
}

function filePathFrom(payload) {
  const input = toolInput(payload);
  return firstString([input.file_path, input.path, input.filename]);
}

function contentFrom(payload) {
  const input = toolInput(payload);
  return [input.content, input.new_string, input.patch, input.diff, input.text]
    .filter(value => typeof value === 'string')
    .join('\n');
}

function isLocalSecretFile(filePath) {
  const name = basename(filePath);
  return /^\.env(?:\.(?!example$|template$)[A-Za-z0-9_-]+)?$/.test(name);
}

function findSecret(content) {
  for (const { pattern, label } of SECRET_PATTERNS) {
    if (pattern.test(content)) return label;
  }
  const assignment = content.match(SECRET_ASSIGNMENT);
  if (assignment && !PLACEHOLDER.test(assignment[1].trim())) return 'credential assignment';
  return null;
}

export function inspectPreTool(payload) {
  const name = toolName(payload);
  if (SHELL_TOOLS.has(name)) {
    const command = commandFrom(payload);
    for (const { pattern, label } of DANGEROUS_COMMANDS) {
      if (pattern.test(command)) return { blocked: true, reason: `위험한 명령이 차단되었습니다: ${label}` };
    }
  }

  if (WRITE_TOOLS.has(name)) {
    const filePath = filePathFrom(payload);
    if (!isLocalSecretFile(filePath)) {
      const secret = findSecret(contentFrom(payload));
      if (secret) return { blocked: true, reason: `파일에 ${secret}이(가) 포함되어 쓰기가 차단되었습니다.` };
    }
  }

  return { blocked: false };
}

export function postToolNotice(payload) {
  if (!WRITE_TOOLS.has(toolName(payload))) return null;
  const filePath = filePathFrom(payload).replaceAll('\\', '/');
  const skillChanged = filePath.startsWith('.agents/skills/') || filePath.startsWith('.claude/skills/');
  const harnessChanged = skillChanged
    || filePath.startsWith('docs/spec/')
    || filePath.startsWith('docs/sources/')
    || filePath.startsWith('tests/acceptance/')
    || filePath === 'docs/decisions.md'
    || filePath.startsWith('harness/')
    || filePath === '.claude/settings.json'
    || filePath === '.codex/hooks.json';

  if (!harnessChanged) return null;
  const commands = [];
  if (skillChanged) commands.push('npm run harness:sync');
  commands.push('npm run harness:check');
  return `[harness] ${filePath || '하네스 관련 파일'} 변경됨. 실행 권장: ${commands.join(' 후 ')}`;
}

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return Buffer.concat(chunks).toString('utf8');
}

function parsePayload(raw) {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

const mode = process.argv[2] ?? '';
if (mode) {
  const payload = parsePayload(await readStdin());
  if (payload) {
    if (mode.endsWith('-pre')) {
      const result = inspectPreTool(payload);
      if (result.blocked) {
        if (mode.startsWith('codex')) {
          console.log(JSON.stringify({
            hookSpecificOutput: {
              hookEventName: 'PreToolUse',
              permissionDecision: 'deny',
              permissionDecisionReason: result.reason
            }
          }));
        } else {
          console.error(`[harness] ${result.reason}`);
          process.exitCode = 2;
        }
      }
    } else if (mode.endsWith('-post')) {
      const notice = postToolNotice(payload);
      if (notice) console.error(notice);
    }
  }
}
