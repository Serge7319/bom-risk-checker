# Cadivor BOM Check for KiCad

This first integration milestone adds a PCB Editor action that reads populated
footprints through KiCad's IPC API, submits their BOM fields to Cadivor, and
opens the saved report in the user's browser. It targets KiCad 9.0.5 or newer
and uses the official `kicad-python` IPC binding; it does not use the legacy
SWIG `pcbnew` plugin API.

## What it sends

The plugin sends one BOM row per distinct manufacturer part number, manufacturer,
description, value, and footprint. Quantity and reference designators are
aggregated. It sends only:

- Manufacturer part number (`MPN`, `Manufacturer Part Number`, `Mfr Part Number`,
  or `Part Number` custom field)
- Manufacturer (`Manufacturer`, `Mfr`, or `Maker` custom field)
- Description (custom field or the KiCad Value field)
- Quantity, reference designators, Value, and Footprint

The board file, schematic, placement, nets, and routing are not uploaded.
Footprints marked `Exclude from BOM` or `Do not populate` are omitted. If any
included footprint lacks an MPN or reference designator, submission stops and
Cadivor receives nothing. There is a confirmation prompt before the upload.

## Requirements

- KiCad 9.0.5 or newer with **Enable KiCad API** turned on in the standalone
  **Preferences → Plugins** page
- Cadivor Developer API access and a workspace API key
- A supported operating-system keychain (macOS Keychain, Windows credential
  store, or a Linux Secret Service backend)

## Install

1. Unzip the download and copy the whole `kicad-cadivor` folder into the
   versioned `plugins` directory. Keep `plugin.json` directly inside that
   folder. Typical locations are:
   - macOS: `~/Documents/KiCad/<version>/plugins/kicad-cadivor/`
   - Windows: `%USERPROFILE%\Documents\KiCad\<version>\plugins\kicad-cadivor\`
   - Linux: `~/.local/share/KiCad/<version>/plugins/kicad-cadivor/`

   Replace `<version>` with your installed KiCad version folder, such as
   `9.0` or `10.0`. The resulting path must end with
   `plugins/kicad-cadivor/plugin.json`.
2. In KiCad's Preferences dialog, select the standalone **Plugins** page near
   the bottom of the left sidebar and check **Enable KiCad API**. The separate
   **PCB Editor → Plugins** page lists detected actions; confirm that
   **Analyze BOM with Cadivor** appears there and **Show Button** is checked.
   On macOS, **Reveal Preferences in Finder** opens KiCad's settings folder,
   not the plugin installation folder.
3. Click **OK**, fully quit and reopen KiCad. KiCad creates an isolated Python
   environment and installs this plugin's dependencies on first launch, so the
   toolbar action may take a little while to appear.
4. In Cadivor, open **APIs** from the workspace navigation and create a
   key. Cadivor shows the secret once; paste it into the plugin prompt on its
   first run. The plugin saves it in your operating-system credential store:
   macOS Keychain, Windows Credential Manager, or the configured Linux Secret
   Service. It remains available across KiCad restarts and Cadivor website
   logouts, so you do not need to create or paste a key for every analysis. You
   do not need to open Credential Manager or Keychain Access for normal use.
   The key is not saved in the project or plugin source files.
5. Open a board in PCB Editor and launch **Analyze BOM with Cadivor** from
   **Tools → External Plugins** or click its Cadivor BOM button in the top
   toolbar. Review the confirmation before the component BOM is sent.

### Windows quick setup

1. In PCB Editor, open **Preferences → PCB Editor → Plugins** and click the
   folder button below the plugin list. This opens KiCad's user plugin folder.
   The default folder is
   `%USERPROFILE%\Documents\KiCad\<version>\plugins` (for example,
   `%USERPROFILE%\Documents\KiCad\10.0\plugins`).
2. Unzip the Cadivor download and copy the complete `kicad-cadivor` folder into
   that `plugins` folder. Confirm that `plugin.json` is directly inside
   `kicad-cadivor`, alongside `cadivor_action.py` and `requirements.txt`.
3. In the standalone **Preferences → Plugins** page, make sure **Enable KiCad
   API** is checked. Return to **PCB Editor → Plugins**, refresh the list if
   needed, and make sure **Show Button** is checked for **Analyze BOM with
   Cadivor**.
4. Click **OK**, fully quit and reopen KiCad, then allow the plugin's Python
   environment setup to finish. Run the action from **Tools → External
   Plugins** or its toolbar button.
5. On the first run, paste your Cadivor developer API key into the prompt. The
   plugin saves it in the Windows credential store for later runs. Logging out
   of Cadivor in your browser does not erase the saved key.

If KiCad uses a customized user-data directory, use the folder button in
**PCB Editor → Plugins** to find the correct plugin folder instead of relying
on the default path above.

### If the action is missing

- Check **Preferences → Plugins** (the standalone page) and confirm
  **Enable KiCad API** is checked.
- In **Preferences → PCB Editor → Plugins**, confirm the Cadivor action is
  listed and **Show Button** is checked.
- In PCB Editor, choose **Tools → External Plugins → Refresh Plugins**, then
  reopen **Tools → External Plugins** and check for **Analyze BOM with Cadivor**.
- If the action is listed in **Preferences → PCB Editor → Plugins** but is
  still missing from the menu, right-click its row and choose **Recreate Plugin
  Environment** (on macOS, use a two-finger click on a trackpad). Wait for
  setup to finish, then close and reopen the PCB Editor.
- If KiCad reports a plugin setup error, open **Preferences → PCB Editor →
  Plugins** and use the warning/errors control at the bottom of that page for
  details. The API listening message only confirms that KiCad's API server is
  running; it does not confirm that this plugin action has loaded.
- Confirm the file is at
  `.../plugins/kicad-cadivor/plugin.json`, not one folder deeper.
- Restart KiCad and allow the first-run Python environment setup to finish.
- Confirm KiCad is version 9.0.5 or newer.
- If a report shows component names such as
  `BoardText(value=LM358DR, position=Vector2(...), layer=...)`, the older
  action sent KiCad text-object metadata instead of the visible component
  text. The current action reads the visible value directly, and Cadivor's BOM
  intake can recover this known legacy wrapper while marking it in the intake
  review. A report already saved from the wrapped value is not refreshed or
  repaired in place: do not rely on its affected supplier matches or risk
  results. Install the current plugin, then create a new analysis or use
  **Edit BOM / new revision** to correct the affected MPN and manufacturer
  fields before analyzing again.

### If clicking the action appears to do nothing

- Check KiCad's plugin/action messages for the error. A message that ends in
  `TclError: Can't find a usable init.tcl` means an older Cadivor plugin tried
  to open its API-key prompt with Tkinter, but KiCad's bundled Python could not
  find the Tcl/Tk files it needs. You do not need to install Tcl/Tk manually.
- Replace the installed `kicad-cadivor` folder with the one from the latest
  Cadivor plugin download, then fully quit and reopen KiCad. The updated macOS
  action uses native system dialogs for the API-key prompt, confirmation, and
  result messages. On Windows, the action uses dialogs provided by KiCad's
  Python environment.
- On the first click after installing the update, expect the Cadivor API-key
  prompt. After saving the key, the action asks you to confirm before sending
  BOM rows. If the board has included footprints without an MPN custom field,
  it stops and lists the references to fix; it does not upload an incomplete
  BOM.
- If the updated action still exits, copy the complete KiCad action error
  message when asking for support. The traceback identifies whether the
  failure is in the dialog, KiCad connection, BOM fields, or API request.

### If the action says Cadivor could not be reached

- Open `https://cadivor-next-api-prod-production.up.railway.app/health` in a
  browser. A JSON response with `"ok": true` confirms that the browser can
  reach the API host; it does not test the network connection from KiCad's
  bundled Python.
- The plugin includes the Certifi Mozilla CA bundle and uses it for HTTPS
  certificate checks. If you get the certificate error from an older plugin,
  replace the installed `kicad-cadivor` folder with the latest download, then
  open **Preferences → PCB Editor → Plugins**, right-click the Cadivor action,
  choose **Recreate Plugin Environment**, wait for setup to finish, and restart
  KiCad. This installs the CA bundle into the plugin environment.
- The updated action reports whether the failure was TLS verification, DNS, or
  a timeout when it can identify the cause. Keep the complete message for
  troubleshooting. If TLS still fails, check your Mac's date and time and
  whether a VPN or security tool inspects HTTPS. Do not disable certificate
  verification. HTTP 401/403 responses are shown separately and indicate an
  invalid/revoked key or inactive API access, rather than a connection failure.

The first version uses Cadivor production by default. To point at another
deployment for development, set `CADIVOR_API_BASE` before launching KiCad. The
value must use HTTPS. `CADIVOR_APP_BASE` can override the report link's app host.

## MPN setup in KiCad

Add a custom symbol/footprint field named `MPN` or `Manufacturer Part Number`
to each populated component before updating the PCB from the schematic. Keep
the actual manufacturer part number in that field; the plugin never guesses an
MPN from the component Value. The optional Manufacturer and Description fields
are named in the table above.

## Billing and analysis behavior

The API uses the same Cadivor analysis and workspace limits as the signed-in
application. It does not start one-time-report checkout or charge a payment
method. The request waits for analysis to finish, then opens the saved report.
Analysis may use supplier integrations enabled for that Cadivor environment.

Revoke the plugin key in Cadivor’s **APIs** workspace page. Deleting
the key from the operating-system keychain only removes it from this computer;
revocation in Cadivor disables it everywhere.
