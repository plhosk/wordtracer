import { execFileSync, spawn } from 'node:child_process';
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

function gitTimestamp() {
  const output = execFileSync('git', ['log', '-1', '--format=%ct'], {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'ignore'],
  }).trim();
  if (!output) {
    throw new Error('Could not read git timestamp for SOURCE_DATE_EPOCH');
  }
  return output;
}

async function main() {
  const sourceDateEpoch = gitTimestamp();
  const buildEnv = {
    ...process.env,
    TZ: 'UTC',
    LC_ALL: 'C.UTF-8',
    LANG: 'C.UTF-8',
    SOURCE_DATE_EPOCH: sourceDateEpoch,
  };

  console.log(`SOURCE_DATE_EPOCH=${sourceDateEpoch}`);

  const installCode = await run(npmCmd, ['ci'], { env: buildEnv });
  if (installCode !== 0) {
    process.exit(installCode);
  }

  const syncCode = await run(npmCmd, ['run', 'cap:sync'], { env: buildEnv });
  if (syncCode !== 0) {
    process.exit(syncCode);
  }

  const gradleCode = await run(gradleCmd, ['clean', 'assembleRelease'], {
    cwd: 'android',
    env: buildEnv,
  });
  if (gradleCode !== 0) {
    process.exit(gradleCode);
  }

  console.log('unsigned apk: android/app/build/outputs/apk/release/app-release-unsigned.apk');
}

await main();
