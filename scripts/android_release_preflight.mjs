import { execFileSync } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import process from 'node:process';

function usage() {
  console.log('Usage: node scripts/android_release_preflight.mjs [version]');
  console.log('');
  console.log('If version is omitted, package.json version is used.');
}

function parseFirst(content, pattern, label) {
  const match = content.match(pattern);
  if (!match) {
    throw new Error(`Could not read ${label}`);
  }
  return match[1];
}

function gitOutput(args) {
  return execFileSync('git', args, {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'ignore'],
  }).trim();
}

async function readReleaseFields() {
  const packageJsonRaw = await readFile('package.json', 'utf8');
  const gradleRaw = await readFile('android/app/build.gradle', 'utf8');
  const metadataRaw = await readFile('metadata/com.wordtracer.app.yml', 'utf8');

  let packageJson;
  try {
    packageJson = JSON.parse(packageJsonRaw);
  } catch {
    throw new Error('Could not parse package.json');
  }

  const packageVersion = String(packageJson.version || '').trim();
  if (!packageVersion) {
    throw new Error('package.json missing version');
  }

  const gradleVersion = parseFirst(
    gradleRaw,
    /^\s*versionName\s+"([^"]+)"\s*$/m,
    'Gradle versionName'
  );
  const gradleCode = Number.parseInt(
    parseFirst(gradleRaw, /^\s*versionCode\s+(\d+)\s*$/m, 'Gradle versionCode'),
    10
  );

  const metadataBuildVersion = parseFirst(
    metadataRaw,
    /^\s*-\s*versionName:\s*(\S+)\s*$/m,
    'metadata Builds versionName'
  );
  const metadataBuildCode = Number.parseInt(
    parseFirst(metadataRaw, /^\s*versionCode:\s*(\d+)\s*$/m, 'metadata Builds versionCode'),
    10
  );
  const metadataCurrentVersion = parseFirst(
    metadataRaw,
    /^\s*CurrentVersion:\s*(\S+)\s*$/m,
    'metadata CurrentVersion'
  );
  const metadataCurrentCode = Number.parseInt(
    parseFirst(metadataRaw, /^\s*CurrentVersionCode:\s*(\d+)\s*$/m, 'metadata CurrentVersionCode'),
    10
  );
  const metadataCommit = parseFirst(metadataRaw, /^\s*commit:\s*(\S+)\s*$/m, 'metadata commit');

  return {
    packageVersion,
    gradleVersion,
    gradleCode,
    metadataBuildVersion,
    metadataBuildCode,
    metadataCurrentVersion,
    metadataCurrentCode,
    metadataCommit,
  };
}

function addMismatchErrors(errors, values, expectedVersion) {
  const mismatched = Object.entries(values).filter((entry) => entry[1] !== expectedVersion);
  for (const entry of mismatched) {
    errors.push(`Version mismatch: ${entry[0]}=${entry[1]}, expected ${expectedVersion}`);
  }
}

function checkGitState(errors, expectedTag) {
  let dirtyOutput;
  try {
    dirtyOutput = gitOutput(['status', '--porcelain']);
  } catch {
    errors.push('Could not read git status');
    return;
  }

  if (dirtyOutput) {
    errors.push('Working tree is not clean (commit/stash changes before release preflight)');
  }

  let headTag;
  try {
    headTag = gitOutput(['describe', '--tags', '--exact-match', 'HEAD']);
  } catch {
    errors.push(`HEAD is not exactly on tag ${expectedTag}`);
    return;
  }

  if (headTag !== expectedTag) {
    errors.push(`HEAD tag is ${headTag}, expected ${expectedTag}`);
  }
}

async function main() {
  const args = process.argv.slice(2);
  if (args.includes('-h') || args.includes('--help')) {
    usage();
    return;
  }
  if (args.length > 1) {
    usage();
    process.exit(1);
  }

  const fields = await readReleaseFields();
  const expectedVersion = (args[0] || fields.packageVersion).trim();
  if (!/^\d+\.\d+\.\d+$/.test(expectedVersion)) {
    throw new Error(`Version must look like X.Y.Z (got ${expectedVersion})`);
  }

  const expectedTag = `v${expectedVersion}`;
  const versionValues = {
    'package.json version': fields.packageVersion,
    'android/app/build.gradle versionName': fields.gradleVersion,
    'metadata Builds.versionName': fields.metadataBuildVersion,
    'metadata CurrentVersion': fields.metadataCurrentVersion,
  };
  const codeValues = {
    'android/app/build.gradle versionCode': fields.gradleCode,
    'metadata Builds.versionCode': fields.metadataBuildCode,
    'metadata CurrentVersionCode': fields.metadataCurrentCode,
  };

  const errors = [];
  addMismatchErrors(errors, versionValues, expectedVersion);

  const codeSet = new Set(Object.values(codeValues));
  if (codeSet.size !== 1) {
    const details = Object.entries(codeValues)
      .map((entry) => `${entry[0]}=${entry[1]}`)
      .join(', ');
    errors.push(`Version code mismatch: ${details}`);
  }

  if (fields.metadataCommit !== expectedTag) {
    errors.push(`Metadata commit is ${fields.metadataCommit}, expected ${expectedTag}`);
  }

  checkGitState(errors, expectedTag);

  if (errors.length > 0) {
    console.error('Release preflight failed:');
    for (const error of errors) {
      console.error(`- ${error}`);
    }
    process.exit(1);
  }

  const versionCode = Object.values(codeValues)[0];
  console.log('Release preflight passed');
  console.log(`- version: ${expectedVersion}`);
  console.log(`- versionCode: ${versionCode}`);
  console.log(`- tag: ${expectedTag}`);
}

await main();
