import re


def extract_frequency_mhz(text: str):
    text = str(text or "")

    match = re.search(r"(\d+(?:\.\d+)?)\s*MHz", text, re.IGNORECASE)
    if match:
        return float(match.group(1))

    match = re.search(r"(\d+(?:\.\d+)?)\s*kHz", text, re.IGNORECASE)
    if match:
        return float(match.group(1)) / 1000

    return None


def extract_slew_rate_v_us(text: str):
    text = str(text or "")

    match = re.search(r"(\d+(?:\.\d+)?)\s*V\s*/\s*(?:µ|u)s", text, re.IGNORECASE)
    if match:
        return float(match.group(1))

    return None


def extract_voltage_mv(text: str):
    text = str(text or "")

    match = re.search(r"(\d+(?:\.\d+)?)\s*mV", text, re.IGNORECASE)
    if match:
        return float(match.group(1))

    match = re.search(r"(\d+(?:\.\d+)?)\s*µV", text, re.IGNORECASE)
    if match:
        return float(match.group(1)) / 1000

    return None


def extract_current_na(text: str):
    text = str(text or "")

    match = re.search(r"(\d+(?:\.\d+)?)\s*nA", text, re.IGNORECASE)
    if match:
        return float(match.group(1))

    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:µ|u)A", text, re.IGNORECASE)
    if match:
        return float(match.group(1)) * 1000

    match = re.search(r"(\d+(?:\.\d+)?)\s*mA", text, re.IGNORECASE)
    if match:
        return float(match.group(1)) * 1_000_000

    return None


def extract_current_ma(text: str):
    text = str(text or "")

    match = re.search(r"(\d+(?:\.\d+)?)\s*mA", text, re.IGNORECASE)
    if match:
        return float(match.group(1))

    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:µ|u)A", text, re.IGNORECASE)
    if match:
        return float(match.group(1)) / 1000

    match = re.search(r"(\d+(?:\.\d+)?)\s*nA", text, re.IGNORECASE)
    if match:
        return float(match.group(1)) / 1_000_000

    return None