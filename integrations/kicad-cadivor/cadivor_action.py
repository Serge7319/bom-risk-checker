"""KiCad IPC action for sending the open PCB BOM to Cadivor."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import urllib.error
import urllib.request
import uuid
import webbrowser
from typing import Any

import keyring
from kipy import KiCad


API_BASE = os.environ.get(
    "CADIVOR_API_BASE",
    "https://cadivor-next-api-prod-production.up.railway.app",
).strip().rstrip("/")
APP_BASE = os.environ.get("CADIVOR_APP_BASE", "https://app.cadivor.com").strip().rstrip("/")
KEYRING_SERVICE = "Cadivor KiCad integration"
KEYRING_USERNAME = "developer-api-key"
FIELD_NAMES = {
    "mpn": {"mpn", "manufacturerpartnumber", "manufacturerpartno", "mfrpartnumber", "partnumber"},
    "manufacturer": {"manufacturer", "mfr", "maker"},
    "description": {"description", "partdescription"},
}


def _message(title: str, message: str, *, error: bool = False) -> None:
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    try:
        if error:
            messagebox.showerror(title, message, parent=root)
        else:
            messagebox.showinfo(title, message, parent=root)
    finally:
        root.destroy()


def _confirm(message: str) -> bool:
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    try:
        return bool(messagebox.askyesno("Send BOM to Cadivor?", message, parent=root))
    finally:
        root.destroy()


def _get_api_key() -> str | None:
    try:
        backend = keyring.get_keyring()
        if float(getattr(backend, "priority", 0)) <= 0:
            raise RuntimeError("No operating-system credential store is available.")
        saved = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except Exception as exc:  # noqa: BLE001
        _message(
            "Cadivor credential store unavailable",
            f"Cadivor needs a supported operating-system keychain to store its API key. {exc}",
            error=True,
        )
        return None
    if saved:
        return saved

    import tkinter as tk
    from tkinter import simpledialog

    root = tk.Tk()
    root.withdraw()
    try:
        value = simpledialog.askstring(
            "Connect Cadivor",
            "Paste a Cadivor developer API key. It will be saved to your operating-system keychain.",
            show="*",
            parent=root,
        )
    finally:
        root.destroy()
    if value is None:
        return None
    value = value.strip()
    if not value.startswith("cdv_live_"):
        _message("Invalid Cadivor key", "The key must start with cdv_live_.", error=True)
        return None
    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, value)
    except Exception as exc:  # noqa: BLE001
        _message(
            "Could not save Cadivor key",
            f"The API key was not stored. Check your operating-system keychain settings. {exc}",
            error=True,
        )
        return None
    return value


def _plain_text(value: Any) -> str:
    if value is None:
        return ""
    nested = getattr(value, "text", value)
    if not isinstance(nested, str):
        nested = getattr(nested, "text", nested)
    if not isinstance(nested, str):
        nested = str(nested or "")
    return nested.strip()


def _field_map(footprint: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        fields = footprint.texts_and_fields
    except Exception:  # noqa: BLE001
        fields = ()
    for item in fields or ():
        name = re.sub(r"[^a-z0-9]", "", str(getattr(item, "name", "")).casefold())
        if name:
            result[name] = _plain_text(item)
    return result


def _read_named_field(fields: dict[str, str], category: str) -> str:
    for name in FIELD_NAMES[category]:
        if fields.get(name):
            return fields[name]
    return ""


def _is_excluded(footprint: Any) -> bool:
    attributes = getattr(footprint, "attributes", None)
    return bool(
        getattr(attributes, "exclude_from_bill_of_materials", False)
        or getattr(attributes, "do_not_populate", False)
    )


def _footprint_name(footprint: Any) -> str:
    definition = getattr(footprint, "definition", None)
    identifier = getattr(definition, "id", None)
    library = str(getattr(identifier, "library", "") or "").strip()
    name = str(getattr(identifier, "name", "") or "").strip()
    return f"{library}:{name}" if library and name else ""


def _make_bom_csv(footprints: list[Any]) -> tuple[bytes, int, list[str]]:
    grouped: dict[tuple[str, ...], dict[str, Any]] = {}
    missing_mpn: list[str] = []
    included = 0

    for footprint in footprints:
        if _is_excluded(footprint):
            continue
        fields = _field_map(footprint)
        reference = _plain_text(getattr(footprint, "reference_field", None))
        value = _plain_text(getattr(footprint, "value_field", None))
        mpn = _read_named_field(fields, "mpn")
        if not mpn:
            missing_mpn.append(reference or "(unannotated footprint)")
            continue
        if not reference:
            missing_mpn.append("(missing reference designator)")
            continue

        manufacturer = _read_named_field(fields, "manufacturer")
        description = _read_named_field(fields, "description")
        if not description:
            try:
                description = _plain_text(footprint.description_field)
            except Exception:  # noqa: BLE001
                description = ""
        if not description:
            description = value
        footprint_name = _footprint_name(footprint)
        key = tuple(
            item.casefold()
            for item in (mpn, manufacturer, description, value, footprint_name)
        )
        row = grouped.setdefault(
            key,
            {
                "Manufacturer Part Number": mpn,
                "Manufacturer": manufacturer,
                "Description": description,
                "Quantity": 0,
                "Reference Designators": [],
                "Value": value,
                "Footprint": footprint_name,
            },
        )
        row["Quantity"] += 1
        row["Reference Designators"].append(reference)
        included += 1

    if missing_mpn:
        return b"", included, missing_mpn

    output = io.StringIO(newline="")
    columns = [
        "Manufacturer Part Number",
        "Manufacturer",
        "Description",
        "Quantity",
        "Reference Designators",
        "Value",
        "Footprint",
    ]
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    for row in sorted(grouped.values(), key=lambda item: item["Reference Designators"][0]):
        row["Reference Designators"] = " ".join(sorted(row["Reference Designators"]))
        writer.writerow(row)
    return output.getvalue().encode("utf-8-sig"), included, []


def _multipart(fields: dict[str, str], filename: str, content: bytes) -> tuple[bytes, str]:
    boundary = "CadivorKiCad" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
            b"Content-Type: text/csv; charset=utf-8\r\n\r\n",
            content,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks), boundary


def _send_bom(api_key: str, csv_bytes: bytes, component_count: int) -> dict[str, Any]:
    if not API_BASE.startswith("https://"):
        raise ValueError("CADIVOR_API_BASE must use HTTPS.")
    body, boundary = _multipart(
        {"project_name": "KiCad", "bom_name": "KiCad PCB BOM"},
        "kicad-bom.csv",
        csv_bytes,
    )
    request = urllib.request.Request(
        f"{API_BASE}/v1/analyses",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=18 * 60) as response:
            payload = json.loads(response.read(1_000_000).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read(64_000).decode("utf-8"))
            detail = str(payload.get("detail") or "Cadivor could not analyze this BOM.")
        except (UnicodeDecodeError, json.JSONDecodeError):
            detail = "Cadivor could not analyze this BOM. Check your API access and BOM format."
        raise RuntimeError(detail) from None
    except (TimeoutError, urllib.error.URLError, OSError):
        raise RuntimeError("Cadivor could not be reached. Check your connection and try again.") from None
    if not isinstance(payload, dict) or not payload.get("analysis_id"):
        raise RuntimeError("Cadivor returned an incomplete analysis response.")
    payload["component_count_sent"] = component_count
    return payload


def main() -> None:
    api_key = _get_api_key()
    if not api_key:
        return

    kicad = None
    try:
        kicad = KiCad()
        board = kicad.get_board()
        if board is None:
            _message("No PCB open", "Open a PCB in KiCad's PCB Editor, then run Cadivor BOM Check.", error=True)
            return
        footprints = list(board.get_footprints())
        csv_bytes, component_count, missing_mpn = _make_bom_csv(footprints)
        if missing_mpn:
            sample = "\n".join(missing_mpn[:12])
            remainder = len(missing_mpn) - min(len(missing_mpn), 12)
            if remainder:
                sample += f"\n…and {remainder} more"
            _message(
                "Resolve BOM fields",
                "Cadivor did not receive anything. Add an MPN custom field and a reference designator to every included footprint before analysis:\n\n"
                + sample,
                error=True,
            )
            return
        if component_count == 0:
            _message("No BOM parts found", "This board has no populated, BOM-included footprints to analyze.", error=True)
            return
        if not _confirm(
            f"Send {component_count} populated board components to Cadivor for analysis?\n\n"
            "Cadivor receives the MPN, manufacturer, description, quantity, references, value, and footprint. "
            "The KiCad board file, schematic, placement, and routing are not uploaded. "
            "If supplier checks are enabled, Cadivor may send the supplied MPNs to those providers."
        ):
            return
        result = _send_bom(api_key, csv_bytes, component_count)
        report_url = str(result.get("report_url") or "").strip()
        if not report_url:
            report_url = f"{APP_BASE}/reports/{result['analysis_id']}"
        webbrowser.open(report_url)
        _message(
            "Cadivor analysis complete",
            f"Saved report {result['analysis_id']} for {component_count} components.\n\n"
            f"Status: {result.get('health_status', 'Ready')}\n"
            f"High-risk findings: {result.get('high_risk_count', '—')}\n\n"
            "The saved report is opening in your browser.",
        )
    except Exception as exc:  # noqa: BLE001
        _message("Cadivor BOM Check failed", str(exc), error=True)
    finally:
        if kicad is not None:
            try:
                kicad.close()
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    main()
