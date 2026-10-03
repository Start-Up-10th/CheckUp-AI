import { cpSync, existsSync, lstatSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const manifest = JSON.parse(readFileSync(path.join(ROOT, 'harness/ai-integration.json'), 'utf8'));

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
if (!existsSync(source)) throw new Error(`AI-feat 작업 폴더를 찾을 수 없음: ${source}`);

let copied = 0;
for (const relative of manifest.paths) {
  const from = within(source, relative);
  const to = within(ROOT, relative);
  if (!existsSync(from)) throw new Error(`AI-feat 허용 목록 파일이 없음: ${relative}`);
  if (lstatSync(from).isSymbolicLink()) throw new Error(`심볼릭 링크는 통합하지 않음: ${relative}`);
  cpSync(from, to, { recursive: true, force: true });
  copied++;
}

console.log(`AI-feat → entire-AI 통합 완료: ${copied}개 경로`);
