import { cp, mkdir, stat } from 'node:fs/promises';
import process from 'node:process';

const sourceIconPath = 'public/icon3000.png';
const resourcesDir = 'resources';
const targetIconPath = 'resources/icon.png';

try {
  await stat(sourceIconPath);
} catch {
  console.error(`missing source icon: ${sourceIconPath}`);
  process.exit(1);
}

await mkdir(resourcesDir, { recursive: true });
await cp(sourceIconPath, targetIconPath);
