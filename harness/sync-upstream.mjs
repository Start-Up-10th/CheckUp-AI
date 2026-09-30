import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const manifest = JSON.parse(readFileSync(path.join(ROOT, 'harness/upstream-manifest.json'), 'utf8'));

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

console.log('ALL_harness updated to origin/main');
