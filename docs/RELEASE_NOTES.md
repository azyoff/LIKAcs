LIKAcs v1.1.0 - professional installation and one-click updates.

NEW - Real installation, still ONE download
  * Double-click LIKAcs.exe: on first run it opens the LIKAcs Setup wizard and
    installs itself per-user (no administrator rights, no UAC).
  * Start Menu shortcuts: LIKAcs, Control Center, Station Agent, likaapps.com.
    Desktop shortcut and optional "start Station Agent with Windows".
  * Proper Windows "Apps & features" entry with a working Uninstall command.
  * Everything is removed cleanly by --mode=uninstall; your cafe settings stay.
  * Silent IT rollout: LIKAcs-Setup.exe --silent --autostart (Actions artifact).

NEW - One click to update, directly from GitHub
  * Prominent "Update LIKAcs" button in the header, Updates tab, tray menu and
    About dialog of both apps. One click checks, downloads, verifies, stages
    and restarts. No manual download, no renaming, no copying files.
  * Reads latest.json from the stable /releases/latest/download/ URL: no API
    rate limits. Cross-checks the SHA-256 in the manifest AND SHA256SUMS.txt.
  * Safe swap: keeps a .bak, verifies the new exe boots with --version, and
    automatically rolls back if it does not. Relaunches with your original
    command line. Nothing is lost if the download or verification fails.
  * Advanced: "Push update to ALL Station PCs" still streams the verified exe
    over the signed LAN to every connected gaming PC.

POLISH - 100x more professional
  * Crisp text on 4K / scaled displays (per-monitor DPI awareness).
  * Only one LIKAcs window can run at a time, with a friendly tray hint.
  * No raw Python traceback dialogs: errors are explained in plain language
    and written to %APPDATA%\LIKAcs\logs\LIKAcs.log with a Copy/Open action.
  * Consistent LIKAcs / likaapps.com branding in the wizard, headers, footers,
    tray, About dialog and every release artifact.

Still 100% free, open-source and VAC-safe. Still Python stdlib only, no
SteamCMD, no game memory access, no DLL injection. http://likaapps.com
