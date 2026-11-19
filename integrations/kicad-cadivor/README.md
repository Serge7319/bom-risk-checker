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

- KiCad 9.0.5 or newer with the IPC API server enabled in Preferences → Plugins
- Cadivor Developer API access and a workspace API key
- A supported operating-system keychain (macOS Keychain, Windows credential
  store, or a Linux Secret Service backend)

## Install

1. Copy this entire `kicad-cadivor` directory into KiCad's versioned `plugins`
   directory. The usual locations are:
   - macOS: `~/Documents/KiCad/9.0/plugins/`
   - Windows: `%USERPROFILE%\Documents\KiCad\9.0\plugins\`
   - Linux: `~/.local/share/KiCad/9.0/plugins/`
2. Restart KiCad. Its IPC plugin manager reads `plugin.json` and installs the
   Python packages in this directory's `requirements.txt` into an isolated
   plugin environment. The action can take a little while to appear while that
   environment is being created.
3. In Cadivor, open Settings → Billing → Developer API and create a key. Cadivor
   shows the key once; copy it directly into the plugin prompt. The plugin
   stores it in the operating-system keychain, never in the project or source
   files.
4. In PCB Editor, choose **Analyze BOM with Cadivor** from the toolbar.

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

Revoke the plugin key in Cadivor Settings → Billing → Developer API. Deleting
the key from the operating-system keychain only removes it from this computer;
revocation in Cadivor disables it everywhere.
