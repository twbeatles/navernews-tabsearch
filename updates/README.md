# Signed update manifest

`latest.json` is generated for each GitHub Release and must be signed with the
private Ed25519 key held outside this repository. Do not commit a private key or
an unsigned placeholder manifest.

Release procedure:

1. Build `NewsScraperPro_Safe.exe` with PyInstaller and upload it to a GitHub
   Release tagged `v<version>`.
2. Set `NEWS_SCRAPER_UPDATE_PRIVATE_KEY_B64` only in the release shell or CI
   secret store.
3. Run:

   ```powershell
   python scripts/build_update_manifest.py --version <version> --artifact dist\NewsScraperPro_Safe.exe --artifact-url https://github.com/twbeatles/navernews-tabsearch/releases/download/v<version>/NewsScraperPro_Safe.exe --output updates\latest.json
   ```

4. Commit and push the generated `updates/latest.json` to `main` after the
   GitHub Release asset is available. The tag-based GitHub Actions workflow
   automates these steps when the release tag matches `core.constants.VERSION`.

The installer replaces only the executable. It does not ship a sidecar
`news_icon.ico`. The Windows app identity uses the executable's embedded icon,
and a successful replace notifies Explorer to refresh that path's icon cache.

If an install fails, the next application start reads `last-update-result.json`
from the runtime `updates/` directory and informs the user whether the previous
executable was restored. Stale staged and helper executables are cleaned on a
later normal app start; do not delete an `updates/` directory while an update is
currently applying.
