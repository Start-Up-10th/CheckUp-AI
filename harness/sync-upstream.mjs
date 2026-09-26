import { cpSync, existsSync, lstatSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const manifest = JSON.parse(readFileSync(path.join(ROOT, 'harness/upstream-manifest.json'), 'utf8'));
const preservePaths = new Set(manifest.preservePaths ?? []);

function within(root, relative) {
  const target = path.resolve(root, relative);
  const rel = path.relative(root, target);
  if (rel === '..' || rel.startsWith(`..${path.sep}`) || path.isAbsolute(rel)) {
    throw new Error(`경로가 저장소 밖을 가리킴: ${relative}`);
  }
  return target;
}

function sibling(root, relative) {
  const target = path.resolve(root, relative);
  if (path.dirname(target) !== path.dirname(root)) {
    throw new Error(`허용되지 않은 외부 경로: ${relative}`);
  }
  return target;
}

const source = sibling(ROOT, manifest.sourceDir);
if (!existsSync(source) || !existsSync(path.join(source, '.git'))) {
  throw new Error(`ALL_harness Git 저장소를 찾을 수 없음: ${source}`);
}

execFileSync('git', ['-C', source, 'fetch', 'origin', 'main'], { stdio: 'inherit' });
execFileSync('git', ['-C', source, 'reset', '--hard', 'origin/main'], { stdio: 'inherit' });

let copied = 0;
for (const relative of manifest.paths) {
  if (preservePaths.has(relative)) {
    throw new Error(`통합 전용 보존 경로를 upstream 동기화 목록에 넣을 수 없음: ${relative}`);
  }
  const from = within(source, relative);
  const to = within(ROOT, relative);
  if (!existsSync(from)) throw new Error(`ALL_harness 원본 파일이 없음: ${relative}`);
  if (lstatSync(from).isSymbolicLink()) throw new Error(`심볼릭 링크는 동기화하지 않음: ${relative}`);
  cpSync(from, to, { recursive: true, force: true });
  copied++;
}

for (const relative of preservePaths) {
  if (!existsSync(within(ROOT, relative))) {
    throw new Error(`통합 전용 보존 파일이 없음: ${relative}`);
  }
}

console.log(`ALL_harness → entire-AI 동기화 완료: ${copied}개 경로`);
