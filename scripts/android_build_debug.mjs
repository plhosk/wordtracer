import { spawn } from 'node:child_process';
import process from 'node:process';

const npmCmd = process.platform === 'win32' ? 'npm.cmd' : 'npm';
const gradleCmd = process.platform === 'win32' ? 'gradlew.bat' : './gradlew';

function run(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      stdio: 'inherit',
      ...options,
    });

    child.on('error', reject);
    child.on('exit', (code, signal) => {
      if (signal) {
        process.kill(process.pid, signal);
        return;
      }

      resolve(code ?? 0);
    });
  });
}

const syncCode = await run(npmCmd, ['run', 'cap:sync']);
if (syncCode !== 0) {
  process.exit(syncCode);
}

const gradleCode = await run(gradleCmd, ['clean', 'assembleDebug'], {
  cwd: 'android',
});
if (gradleCode !== 0) {
  process.exit(gradleCode);
}

console.log('debug apk: android/app/build/outputs/apk/debug/app-debug.apk');
