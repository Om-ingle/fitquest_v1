#!/usr/bin/env python3
"""Report which auth markers an APK actually contains — by count, never by value.

M11 shipped an Android client whose whole failure mode was invisible: the APK
installed on the test device predated the auth work by five days, carried no
sign-in, no token store and no interceptor, and therefore could only ever send
unauthenticated requests. The backend answered those exactly as designed (401 on
REST, 403 on the WebSocket handshake), and the result was read as a backend
fault. `adb install` succeeding is not evidence that the binary changed.

This is the cheap check that closes that gap. Run it against a built APK, or
against one pulled off the device, and it prints class-name and public-URL
occurrence counts. It reads bytes out of the DEX, so a class that was compiled
in appears here even though it is never named in a string.

    # a build output
    python3 apps/app/tools/apk_auth_scan.py \
        apps/app/fitquest/build/outputs/apk/railway/debug/app-railway-debug.apk

    # what is actually installed
    adb shell pm path com.example.mobileapp          # package:/data/app/.../base.apk
    adb pull /data/app/.../base.apk /tmp/installed.apk
    python3 apps/app/tools/apk_auth_scan.py /tmp/installed.apk

Disclosure: it prints counts, class names and public URLs. The Supabase anon key
is never searched for and never echoed — only whether a Supabase project URL was
compiled in at all, which is what `supabase.co` reports. Nothing here needs
network access and nothing writes to the APK.

Exit status is 1 if any required M11 class is missing, so this can gate a build.
"""
import argparse
import sys
import zipfile

# Classes that exist only if the M11 client was compiled in. Absence of any one
# of these means the binary cannot authenticate, whatever else it contains.
REQUIRED_CLASSES = (
    "SupabaseAuthClient",
    "SupabaseAuthApi",
    "AuthInterceptor",
    "AuthSession",
    "EncryptedTokenStore",
    "TokenRefreshAuthenticator",
    "LoginScreen",
)

# Present in an M11 build, reported for completeness rather than required.
OPTIONAL_CLASSES = (
    "AuthTokens",
    "TokenStore",
    "AesGcmCodec",
    "WelcomeScreen",
)

# Backend/identity markers.
#   fitquest-api-production  the deployed backend — expected in the railway flavor
#   10.0.2.2 / 192.168.      flavor fallbacks; must be ABSENT from a railway APK,
#                            since a production build carrying a LAN address is a
#                            configuration leak even though it is not a secret
#   supabase.co / .in        appears only if a SUPABASE_URL was compiled in — i.e.
#                            whether the build was configured for sign-in at all
EXPECTED_MARKERS = ("fitquest-api-production",)
FORBIDDEN_MARKERS = ("10.0.2.2", "192.168.")
INFORMATIONAL_MARKERS = ("supabase.co", "supabase.in")


def _count(blobs: dict[str, bytes], needle: str) -> int:
    """Occurrences of `needle` across every DEX, summed.

    A count and not a boolean: a class referenced from many call sites is far
    more likely to be wired up than one that appears once.
    """
    raw = needle.encode()
    return sum(blob.count(raw) for blob in blobs.values())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("apk", help="path to the .apk to inspect")
    args = parser.parse_args()

    try:
        archive = zipfile.ZipFile(args.apk)
    except (OSError, zipfile.BadZipFile) as exc:
        print(f"not a readable APK: {args.apk} ({exc})", file=sys.stderr)
        return 2

    with archive:
        dex_names = sorted(n for n in archive.namelist() if n.endswith(".dex"))
        if not dex_names:
            print(f"no .dex entries in {args.apk} — is this an APK?", file=sys.stderr)
            return 2
        blobs = {name: archive.read(name) for name in dex_names}

    print(f"APK:  {args.apk}")
    print(f"DEX:  {len(blobs)} file(s), {sum(len(b) for b in blobs.values()):,} bytes")
    print()

    missing = []
    print("M11 auth classes (required):")
    for name in REQUIRED_CLASSES:
        hits = _count(blobs, name)
        if not hits:
            missing.append(name)
        print(f"  {'OK     ' if hits else 'MISSING'} {name:<26} {hits}")

    print("\nM11 auth classes (supporting):")
    for name in OPTIONAL_CLASSES:
        print(f"  {_count(blobs, name):>7}  {name}")

    print("\nBackend markers:")
    for marker in EXPECTED_MARKERS:
        hits = _count(blobs, marker)
        if not hits:
            missing.append(marker)
        print(f"  {'OK     ' if hits else 'MISSING'} {marker:<26} {hits}")
    for marker in FORBIDDEN_MARKERS:
        hits = _count(blobs, marker)
        if hits:
            missing.append(f"{marker} (must be absent)")
        print(f"  {'LEAK   ' if hits else 'absent '} {marker:<26} {hits}")

    print("\nConfiguration markers (informational):")
    for marker in INFORMATIONAL_MARKERS:
        hits = _count(blobs, marker)
        print(f"  {hits:>7}  {marker}")
    if not any(_count(blobs, m) for m in INFORMATIONAL_MARKERS):
        print(
            "          -> no Supabase URL is compiled in: this APK is built but\n"
            "             NOT configured, so sign-in will report \"not configured\".\n"
            "             Fill SUPABASE_URL / SUPABASE_ANON_KEY and rebuild."
        )

    print()
    if missing:
        print(f"FAIL: {len(missing)} problem(s): {', '.join(missing)}")
        return 1
    print("PASS: this APK carries the M11 auth client and the production backend URL.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
