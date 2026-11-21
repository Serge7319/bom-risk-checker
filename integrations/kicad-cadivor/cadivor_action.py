"""KiCad IPC action for sending the open PCB BOM to Cadivor."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
import webbrowser
from typing import Any

try:
    import keyring
except Exception as exc:  # noqa: BLE001
    keyring = None  # type: ignore[assignment]
    _KEYRING_IMPORT_ERROR = exc
else:
    _KEYRING_IMPORT_ERROR = None

try:
    import certifi
except Exception as exc:  # noqa: BLE001
    certifi = None  # type: ignore[assignment]
    _CERTIFI_IMPORT_ERROR = exc
else:
    _CERTIFI_IMPORT_ERROR = None

try:
    from kipy import KiCad
except Exception as exc:  # noqa: BLE001
    KiCad = None  # type: ignore[assignment,misc]
    _KIPY_IMPORT_ERROR = exc
else:
    _KIPY_IMPORT_ERROR = None


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
_KICAD_BOARDTEXT_WRAPPER = re.compile(
    r"^BoardText\(value=(?P<value>.*?),\s*position=Vector2\([^)]*\),\s*layer=.*\)$",
    re.DOTALL,
)


def _tk_message(title: str, message: str, *, error: bool = False) -> None:
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


def _tk_confirm(message: str) -> bool:
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    try:
        return bool(messagebox.askyesno("Send BOM to Cadivor?", message, parent=root))
    finally:
        root.destroy()


def _osascript(script: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["osascript", "-e", script, *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _mac_message(title: str, message: str, *, error: bool = False) -> None:
    icon = "stop" if error else "note"
    script = f'''on run argv
    display dialog (item 2 of argv) with title (item 1 of argv) buttons {{"OK"}} default button "OK" with icon {icon}
end run'''
    result = _osascript(script, title, message)
    if result.returncode != 0:
        detail = result.stderr.strip() or "macOS could not display the dialog."
        raise RuntimeError(detail)


def _mac_confirm(message: str) -> bool:
    script = '''on run argv
    set dialogResult to display dialog (item 2 of argv) with title (item 1 of argv) buttons {"Cancel", "Send BOM"} default button "Send BOM" cancel button "Cancel" with icon note
    return button returned of dialogResult
end run'''
    result = _osascript(script, "Send BOM to Cadivor?", message)
    if result.returncode == 0:
        return result.stdout.strip().endswith("Send BOM")
    if "(-128)" in result.stderr or "User canceled" in result.stderr:
        return False
    detail = result.stderr.strip() or "macOS could not display the confirmation dialog."
    raise RuntimeError(detail)


def _mac_prompt(title: str, message: str) -> str | None:
    script = '''on run argv
    set dialogResult to display dialog (item 2 of argv) default answer "" with title (item 1 of argv) buttons {"Cancel", "Continue"} default button "Continue" cancel button "Cancel" with hidden answer
    return text returned of dialogResult
end run'''
    result = _osascript(script, title, message)
    if result.returncode == 0:
        return result.stdout.rstrip("\r\n")
    if "(-128)" in result.stderr or "User canceled" in result.stderr:
        return None
    detail = result.stderr.strip() or "macOS could not display the API key prompt."
    raise RuntimeError(detail)


def _message(title: str, message: str, *, error: bool = False) -> None:
    try:
        if sys.platform == "darwin":
            _mac_message(title, message, error=error)
        else:
            _tk_message(title, message, error=error)
    except Exception as primary_error:  # noqa: BLE001
        try:
            if sys.platform == "darwin":
                _tk_message(title, message, error=error)
            else:
                _mac_message(title, message, error=error)
        except Exception as fallback_error:  # noqa: BLE001
            print(
                "Cadivor KiCad action could not open a dialog. "
                f"Primary dialog error: {type(primary_error).__name__}; "
                f"fallback dialog error: {type(fallback_error).__name__}.",
                file=sys.stderr,
                flush=True,
            )
            print(f"{title}: {message}", file=sys.stderr, flush=True)


def _confirm(message: str) -> bool:
    try:
        if sys.platform == "darwin":
            return _mac_confirm(message)
        return _tk_confirm(message)
    except Exception as primary_error:  # noqa: BLE001
        try:
            if sys.platform == "darwin":
                return _tk_confirm(message)
            return _mac_confirm(message)
        except Exception as fallback_error:  # noqa: BLE001
            print(
                "Cadivor KiCad action could not open the BOM confirmation dialog. "
                f"Primary dialog error: {type(primary_error).__name__}; "
                f"fallback dialog error: {type(fallback_error).__name__}.",
                file=sys.stderr,
                flush=True,
            )
            return False


def _get_api_key() -> str | None:
    if keyring is None:
        raise RuntimeError(
            "The plugin could not import its keychain dependency. Recreate the Cadivor "
            "plugin environment in KiCad Preferences."
        ) from _KEYRING_IMPORT_ERROR
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

    prompt_title = "Connect Cadivor"
    prompt_message = "Paste a Cadivor developer API key. It will be saved to your operating-system keychain."
    try:
        if sys.platform == "darwin":
            value = _mac_prompt(prompt_title, prompt_message)
        else:
            import tkinter as tk
            from tkinter import simpledialog

            root = tk.Tk()
            root.withdraw()
            try:
                value = simpledialog.askstring(
                    prompt_title,
                    prompt_message,
                    show="*",
                    parent=root,
                )
            finally:
                root.destroy()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "Cadivor could not open the API key prompt. Check KiCad's action messages for details."
        ) from exc
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
    """Return the visible text from KiCad fields without stringifying wrappers.

    IPC fields are wrapped as Field -> BoardText -> value. Converting either
    wrapper with ``str()`` leaks its position and layer into the BOM instead
    of returning the component text.
    """
    pending = [value]
    seen: set[int] = set()
    while pending and len(seen) < 8:
        current = pending.pop(0)
        if current is None:
            continue
        if isinstance(current, str):
            text = current.strip()
            match = _KICAD_BOARDTEXT_WRAPPER.fullmatch(text)
            if match:
                text = match.group("value").strip()
                if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
                    text = text[1:-1]
            return text
        identity = id(current)
        if identity in seen:
            continue
        seen.add(identity)
        for attribute in ("value", "text"):
            try:
                nested = getattr(current, attribute)
            except Exception:  # noqa: BLE001 - KiCad IPC proxies may reject properties
                continue
            if isinstance(nested, str):
                return nested.strip()
            if nested is not None and nested is not current:
                pending.append(nested)
        try:
            rendered = str(current).strip()
        except Exception:  # noqa: BLE001 - KiCad IPC proxies may reject __str__
            continue
        match = _KICAD_BOARDTEXT_WRAPPER.fullmatch(rendered)
        if match:
            text = match.group("value").strip()
            if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
                text = text[1:-1]
            return text
    return ""


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
    if certifi is None:
        raise RuntimeError(
            "The plugin's certificate bundle is missing. Recreate the Cadivor "
            "plugin environment in KiCad Preferences."
        ) from _CERTIFI_IMPORT_ERROR
    tls_context = ssl.create_default_context(cafile=certifi.where())
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
        with urllib.request.urlopen(request, timeout=18 * 60, context=tls_context) as response:
            payload = json.loads(response.read(1_000_000).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read(64_000).decode("utf-8"))
            detail = str(payload.get("detail") or "Cadivor could not analyze this BOM.")
        except (UnicodeDecodeError, json.JSONDecodeError):
            detail = "Cadivor could not analyze this BOM. Check your API access and BOM format."
        raise RuntimeError(detail) from None
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, ssl.SSLCertVerificationError):
            detail = (
                f"TLS certificate verification failed ({reason}). The plugin uses "
                "a bundled Mozilla CA list. If you use a VPN or security tool "
                "that inspects HTTPS, its roo