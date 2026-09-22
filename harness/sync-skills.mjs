import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { ROOT, inside, skillNames } from './check.mjs';

// Mechanical copies only; the canonical skill text always lives in .agents.
export function syncSkills(root = ROOT) {
  const names = skillNames(root);
  const mirror = inside(root, '.claude/skills');
  mkdirSync(mirror, { recursive: true });
  const extra = skillNames(root, '.claude/skills').filter(name => !names.includes(name));
  if (extra.length) throw new Error(`Stale Claude skills require explicit review/removal: ${extra.join(', ')}`);
  // Read all sources first. A missing source must not leave a partial update.
  const copies = names.map(name => ({
    directory: inside(root, `.claude/skills/${name}`),
    target: inside(root, `.claude/skills/${name}/SKILL.md`),
    content: readFileSync(inside(root, `.agents/skills/${name}/SKILL.md`))
  }));
  let changed = 0;
  for (const { directory, target, content } of copies) {
    if (existsSync(target) && content.equals(readFileSync(target))) continue;
    mkdirSync(directory, { recursive: true });
    writeFileSync(target, content);
    changed++;
  }
  return { total: names.length, changed };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const result = syncSkills();
    console.log(`Skills synchronized: ${result.total} total, ${result.changed} changed`);
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
