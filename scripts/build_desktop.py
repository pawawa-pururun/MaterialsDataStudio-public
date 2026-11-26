"""Build and smoke-test a native Linux folder or macOS application bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(arguments: list[str], *, env: dict[str, str] | None = None, timeout: int = 900) -> None:
    subprocess.run(arguments, cwd=ROOT, env=env, check=True, timeout=timeout)


def check_qt_runtime() -> None:
    """Reject the Qt color-space lifetime regression before building a bundle."""
    import PySide6
    from PySide6.QtCore import QVersionNumber, qVersion

    version = qVersion()
    print(f"Building with PySide6 {PySide6.__version__}; Qt {version}", flush=True)
    # QTBUG-147602: Qt 6.11.1 can trap in QImage::toCGImage on macOS 27.2.
    if QVersionNumber.fromString(version) < QVersionNumber(6, 11, 2):
        raise RuntimeError("Qt >= 6.11.2 is required (QTBUG-147602). Run uv sync --frozen --extra dev.")


def run_smoke_tests(executable: Path, work: Path) -> None:
    """Check dependencies offscreen, then exercise Cocoa on macOS."""
    modes = [("packaging", "offscreen")]
    if sys.platform == "darwin":
        modes.append(("native-gui", "cocoa"))
    for mode, qt_platform in modes:
        private = work / mode
        env = {**os.environ, "QT_QPA_PLATFORM": qt_platform,
               "MDS_SETTINGS_DIRECTORY": str(private / "settings"),
               "MDS_RECOVERY_DIRECTORY": str(private / "recovery"),
               "MDS_MATPLOTLIB_CACHE_DIRECTORY": str(private / "matplotlib"),
               "MPLCONFIGDIR": str(private / "matplotlib"),
               "XDG_CONFIG_HOME": str(private / "config"),
               "XDG_DATA_HOME": str(private / "data"), "XDG_CACHE_HOME": str(private / "cache")}
        report = work / f"{mode}-smoke.txt"
        report.unlink(missing_ok=True)
        try:
            run([str(executable), f"--{mode}-smoke-test", str(report)], env=env, timeout=300)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            if report.exists():
                print(report.read_text(encoding="utf-8"), file=sys.stderr)
            raise
        if not report.read_text(encoding="utf-8").startswith("OK\n"):
            raise RuntimeError(f"Frozen application {mode} smoke report is not successful: {report}")


def prepare_user_cache(executable: Path, work: Path) -> bool:
    """Warm this build machine's real user cache without starting the GUI."""
    report = work / "user-cache-preparation.txt"
    report.unlink(missing_ok=True)
    try:
        run([str(executable), "--prepare-runtime-cache", str(report)], timeout=300)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        if report.exists():
            print(report.read_text(encoding="utf-8"), file=sys.stderr)
        print("User cache preparation did not finish; the application will prepare it when needed.", file=sys.stderr)
        return False
    details = report.read_text(encoding="utf-8")
    if not details.startswith("OK\n"):
        print(f"User font cache was not prepared: {details}", file=sys.stderr)
        return False
    print(details, flush=True)
    return True


def build(output: Path, work: Path, *, notary_profile: str = "", warm_user_cache: bool = True) -> Path:
    from materials_data_studio.version import __version__

    machine = {"amd64": "x86_64", "aarch64": "arm64"}.get(platform.machine().lower(), platform.machine().lower())
    targets = json.loads((ROOT / "packaging/desktop_targets.json").read_text(encoding="utf-8"))
    target = next((t for t in targets if t["platform"] == sys.platform and t["machine"] == machine), None)
    if target is None:
        raise ValueError(f"No desktop target for {sys.platform}/{machine}; use build_windows.ps1 on Windows.")
    check_qt_runtime()
    output, work = output.resolve(), work.resolve()
    output.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    dist = work / "dist"
    legal = work / "legal"
    run([sys.executable, "-m", "scripts.prepare_corresponding_sources"], timeout=1800)
    run([sys.executable, "-m", "scripts.collect_licenses", "--output", str(legal)])
    run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--workpath", str(work / "pyinstaller"), "--distpath", str(dist),
         "packaging/materials_data_studio.spec"],
        env={**os.environ, "MDS_LEGAL_DIR": str(legal)},
    )
    folder = dist / ("Materials Data Studio.app" if sys.platform == "darwin" else "MaterialsDataStudio")
    executable = folder / ("Contents/MacOS/MaterialsDataStudio" if sys.platform == "darwin" else "MaterialsDataStudio")
    run_smoke_tests(executable, work)
    if warm_user_cache:
        prepare_user_cache(executable, work)
    artifact = output / f"MaterialsDataStudio-v{__version__}-{target['suffix']}"
    if sys.platform == "darwin":
        identity = os.environ.get("MDS_MAC_SIGN_IDENTITY", "")
        if notary_profile and not identity:
            raise ValueError("Notarization requires MDS_MAC_SIGN_IDENTITY")
        if identity:
            run(["codesign", "--verify", "--deep", "--strict", str(folder)])
        notary_options = ["--keychain-profile", notary_profile, "--wait"]
        if keychain := os.environ.get("MDS_MAC_NOTARY_KEYCHAIN"):
            notary_options += ["--keychain", keychain]
        if notary_profile:
            upload = work / "notarization.zip"
            run(["ditto", "-c", "-k", "--keepParent", str(folder), str(upload)])
            run(["xcrun", "notarytool", "submit", str(upload), *notary_options], timeout=1800)
            run(["xcrun", "stapler", "staple", str(folder)])
        with tempfile.TemporaryDirectory(prefix="mds-dmg-", dir=work) as staging:
            image = Path(staging)
            # Preserve tickets and framework links without merging a previous build.
            run(["ditto", str(folder), str(image / folder.name)])
            (image / "Applications").symlink_to("/Applications", target_is_directory=True)
            run(["hdiutil", "create", "-ov", "-format", "UDZO", "-volname", "Materials Data Studio", "-srcfolder", str(image), str(artifact)])
        if identity:
            run(["codesign", "--sign", identity, "--timestamp", str(artifact)])
        if notary_profile:
            run(["xcrun", "notarytool", "submit", str(artifact), *notary_options], timeout=1800)
            run(["xcrun", "stapler", "staple", str(artifact)])
            run(["xcrun", "stapler", "validate", str(artifact)])
    else:
        (folder / "INSTALL.txt").write_text(
            "Run ./MaterialsDataStudio from this directory. Keep the entire directory together.\n"
            "To add file associations and a launcher, run ./MaterialsDataStudio --register-file-types\n"
            "This registers MDS for your user without changing existing default applications.\n",
            encoding="utf-8",
        )
        with tarfile.open(artifact, "w:gz") as archive:
            archive.add(folder, arcname=folder.name)
    with artifact.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    artifact.with_name(artifact.name + ".sha256").write_text(f"{digest}  {artifact.name}\n", encoding="utf-8")
    print(artifact)
    return artifact


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "release_assets")
    parser.add_argument("--work", type=Path, default=ROOT / ".test-tmp/desktop-build")
    parser.add_argument("--notary-profile", default=os.environ.get("MDS_MAC_NOTARY_PROFILE", ""))
    parser.add_argument("--prepare-user-cache", action=argparse.BooleanOptionalAction,
                        default=not bool(os.environ.get("CI")),
                        help="Prepare this machine's user font cache (default: local builds only)")
    args = parser.parse_args()
    build(args.output, args.work, notary_profile=args.notary_profile, warm_user_cache=args.prepare_user_cache)


if __name__ == "__main__":
    main()
