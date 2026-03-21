# Reproducible Android Builds

This runbook defines the expected release build and verification flow for Android APK reproducibility.

## Canonical Release Flow

From a clean tree at a tagged release commit:

```bash
npm run android:release:preflight
npm run android:build:release:unsigned
npm run android:sign:release
```

Or all-in-one:

```bash
npm run android:release:repro
```

## Required Environment For Signing

- `ANDROID_SDK_ROOT` (or `ANDROID_HOME`)
- `ANDROID_KEYSTORE_FILE`
- `ANDROID_KEY_ALIAS`
- `ANDROID_KEYSTORE_PASSWORD`
- `ANDROID_KEY_PASSWORD` (optional; defaults to `ANDROID_KEYSTORE_PASSWORD`)

Optional:

- `APKSIGNER_BUILD_TOOLS_VERSION` (defaults to `34.0.0`)

## Expected APK Paths

- Unsigned APK: `android/app/build/outputs/apk/release/app-release-unsigned.apk`
- Signed APK default output: `android/app/build/outputs/apk/release/wordtracer-v<version>.apk`

## Hash Verification

Compute hashes:

```bash
sha256sum android/app/build/outputs/apk/release/app-release-unsigned.apk
sha256sum android/app/build/outputs/apk/release/wordtracer-v1.0.5.apk
```

Rebuild from the same tag in a fresh environment and compare hashes. The unsigned APK must match exactly.

## CI Reproducibility Check

The workflow `reproducible-android.yml` builds the same tag twice (`build_a`, `build_b`) and compares unsigned APK hashes.

- Match: workflow passes.
- Mismatch: workflow fails and uploads diagnostics.

## Debugging Mismatches

Start with:

```bash
diffoscope a.apk b.apk
```

Then inspect ZIP metadata:

```bash
zipinfo -v a.apk > zipinfo-a.txt
zipinfo -v b.apk > zipinfo-b.txt
```

Common causes:

- Toolchain drift (Node, Java, build-tools, Gradle, AGP)
- ZIP ordering/metadata differences
- Line-ending differences from cross-platform builds
- Non-deterministic generated artifacts in dependencies/plugins

## F-Droid Integration Checklist

- Add metadata `Binaries` (or per-build `binary`) URL pointing to upstream release APK.
- Add metadata `AllowedAPKSigningKeys` fingerprint for release signing cert.
- Upload release APK with stable name matching metadata URL pattern.
