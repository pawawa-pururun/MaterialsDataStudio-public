# Linux and macOS builds

[日本語](cross_platform.md)

MDS builds as a Linux x86_64 folder in a tar.gz archive and as an Apple Silicon
macOS app in a DMG. Both builds provide the usual analysis workspaces, Graph
Editor, sessions and exports. Python Procedure execution uses Windows isolation
and is available on Windows.

## Build and install

```sh
uv sync --frozen --extra dev
uv run --no-sync python scripts/build_desktop.py
```

The build uses Qt 6.11.2 or newer, checks the matching source archives against
their SHA-256 hashes, collects license notices and runs smoke tests before
packaging. On macOS it also exercises Graph Editor through Cocoa. The resulting
archive and its checksum are in `release_assets/`.

- On Linux, extract the archive, keep its contents together and run
  `./MaterialsDataStudio`. For desktop launchers and document associations, run
  `./MaterialsDataStudio --register-file-types` or use Preferences.
- On macOS, open the DMG and copy **Materials Data Studio.app** to Applications.
  Finder can open session and graph documents. Developer ID signing and
  notarization are available through the build's signing identity and notarytool
  profile. Use signed and notarized builds for general distribution.

PR checks exercise Windows and Linux. Run `ci.yml` or `desktop-packages.yml`
with `platform=macos` for the Apple Silicon runner. Native package workflows
produce build artifacts. Distribute binaries with matching application and
corresponding library sources using the published release rules.
[Detailed Japanese build guide](cross_platform.md) ·
[Licenses and corresponding source](building_and_licenses.md) ·
[Publication rules](maintainers/publication_policy.md)
