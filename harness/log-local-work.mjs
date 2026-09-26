import { appendFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const message = process.argv.slice(2).join(' ').trim();
if (!message) {
  console.error('사용법: npm run harness:worklog -- "작업 내용과 검증 결과"');
  process.exitCode = 1;
} else {
  const formatter = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit'
  });
  const date = formatter.format(new Date());
  const filename = path.join(ROOT, 'harness/local-worklog.md');
  if (!existsSync(filename)) throw new Error('harness/local-worklog.md가 없음');
  appendFileSync(filename, `\n- ${date}: ${message}\n`, 'utf8');
  console.log(`로컬 하네스 작업 기록 완료: ${date}`);
}
