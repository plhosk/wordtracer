import { spawn } from 'node:child_process';
import { access, readFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

function usage() {
  console.log('Usage: node scripts/android_sign_release.mjs [options]');
  console.log('');
  console.log('Options:');
  console.log('  --input <path>          Unsigned APK path');
  console.log('  --output <path>         Signed APK output path');
  console.log('  --keystore <path>       Keystore file path');
  console.log('  --alias <name>          Keystore alias');
  console.log('  --build-tools <version> Build-tools version used for apksigner');
  console.log('');
  console.log('Environment:');
  console.log('  ANDROID_SDK_ROOT (or ANDROID_HOME)');
  console.log('  ANDROID_KEYSTORE_FILE (if --keystore is omitted)');
  console.log('  ANDROID_KEY_ALIAS (if --alias is omitted)');
  console.log('  ANDROID_KEYSTORE_PASSWORD (required)');
  console.log('  ANDROID_KEY_PASSWORD (optional; defaults to ANDROID_KEYSTORE_PASSWORD)');
}

function parseArgs(argv) {
  const options = {
    input: 'android/app/build/outputs/apk/release/app-release-unsigned.apk',
    output: '',
    keystore: '',
    alias: '',
    buildTools: process.env.APKSIGNER_BUILD_TOOLS_VERSION || '34.0.0',
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--help' || arg === '-h') {
      options.help = true;
      continue;
    }

    if (arg === '--input' || arg === '--output' || arg === '--keystore' || arg === '--alias' || arg === '--build-tools') {
      const value = argv[i + 1];
      if (!value) {
        throw new Error(`Missing value for ${arg}`);
      }
      if (arg === '--input') {
        options.input = value;
      } else if (arg === '--output') {
        options.output = value;
      } else if (arg === '--keystore') {
        options.keystore = value;
      } else if (arg === '--alias') {
        options.alias = value;
      } else {
        options.buildTools = value;
      }
      i += 1;
      continue;
    }

    throw new Error(`Unknown argument: ${arg}`);
  }

  return options;
}

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

async function packageVersion() {
  const raw = await readFile('package.json', 'utf8');
  const parsed = JSON.parse(raw);
  const version = String(parsed.version || '').trim();
  if (!version) {
    throw new Error('package.json missing version');
  }
  return version;
}

async function ensureFile(filePath, label) {
  try {
    await access(filePath);
  } catch {
    throw new Error(`${label} not found: ${filePath}`);
  }
}

function resolveApksigner(buildToolsVersion) {
  const sdkRoot = process.env.ANDROID_SDK_ROOT || process.env.ANDROID_HOME;
  if (!sdkRoot) {
    throw new Error('ANDROID_SDK_ROOT (or ANDROID_HOME) is required');
  }
  return path.join(sdkRoot, 'build-tools', buildToolsVersion, process.platform === 'win32' ? 'apksigner.bat' : 'apksigner');
}

async function main() {
  const options = parseArgs(process.argv.slice(2));
  if (options.help) {
    usage();
    return;
  }

  const version = await packageVersion();
  const inputApk = options.input;
  const outputApk = options.output || `android/app/build/outputs/apk/release/wordtracer-v${version}.apk`;
  const keystore = options.keystore || process.env.ANDROID_KEYSTORE_FILE || '';
  const alias = options.alias || process.env.ANDROID_KEY_ALIAS || '';
  const storePassword = process.env.ANDROID_KEYSTORE_PASSWORD || '';
  const keyPassword = process.env.ANDROID_KEY_PASSWORD || storePassword;

  if (!keystore) {
    throw new Error('Keystore path required via --keystore or ANDROID_KEYSTORE_FILE');
  }
  if (!alias) {
    throw new Error('Key alias required via --alias or ANDROID_KEY_ALIAS');
  }
  if (!storePassword) {
    throw new Error('ANDROID_KEYSTORE_PASSWORD is required');
  }

  await ensureFile(inputApk, 'Unsigned APK');
  await ensureFile(keystore, 'Keystore');

  const apksigner = resolveApksigner(options.buildTools);
  await ensureFile(apksigner, 'apksigner');

  const env = {
    ...process.env,
    ANDROID_KEYSTORE_PASSWORD: storePassword,
    ANDROID_KEY_PASSWORD: keyPassword,
  };

  const signCode = await run(
    apksigner,
    [
      'sign',
      '--ks',
      keystore,
      '--ks-key-alias',
      alias,
      '--ks-pass',
      'env:ANDROID_KEYSTORE_PASSWORD',
      '--key-pass',
      'env:ANDROID_KEY_PASSWORD',
      '--out',
      outputApk,
      inputApk,
    ],
    { env }
  );
  if (signCode !== 0) {
    process.exit(signCode);
  }

  const verifyCode = await run(apksigner, ['verify', '--verbose', '--print-certs', outputApk], {
    env,
  });
  if (verifyCode !== 0) {
    process.exit(verifyCode);
  }

  console.log(`signed apk: ${outputApk}`);
}

await main();
