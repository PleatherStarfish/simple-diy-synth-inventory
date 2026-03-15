"""
BOM Normalizer Service
Normalizes raw BOM items: cleans values, classifies types, extracts part numbers.
"""
from __future__ import annotations

import re

import pandas as pd

from eurorack_inventory.domain.models import NormalizedBomItem, RawBomItem


def normalize(raw_items: list[RawBomItem]) -> list[NormalizedBomItem]:
    """Normalize a list of raw BOM items into cleaned, classified items."""
    results: list[NormalizedBomItem] = []

    for raw in raw_items:
        value = raw.raw_description.strip()
        if not value or not _is_valid_component(value):
            continue

        norm_value, comp_type = _normalize_value(value)
        if not norm_value or comp_type == "skip":
            continue

        qty = _clean_quantity(raw.raw_qty)
        all_text = " ".join(
            s for s in [value, raw.raw_notes or ""] if s
        )
        package = _extract_package(all_text)
        tayda = _extract_tayda_pn(all_text)
        mouser = _extract_mouser_pn(all_text)

        results.append(
            NormalizedBomItem(
                id=None,
                bom_source_id=raw.bom_source_id,
                raw_item_id=raw.id if raw.id is not None else 0,
                component_type=comp_type,
                normalized_value=norm_value,
                qty=qty,
                package_hint=package or None,
                reference=None,
                tayda_pn=tayda or None,
                mouser_pn=mouser or None,
            )
        )

    return results


# ── Quantity Parsing ────────────────────────────────────────────────────


def _clean_quantity(qty) -> int:
    if pd.isna(qty) or qty == "":
        return 1
    qty = str(qty).strip()
    if qty.endswith(".0"):
        qty = qty[:-2]

    m = re.match(r"^(\d+)\s*x\s*(\d+)", qty, re.I)
    if m:
        return int(m.group(1)) * int(m.group(2))

    m = re.match(r"^(\d+)", qty)
    if m:
        return max(1, int(m.group(1)))
    return 1


# ── Part Number Extraction ──────────────────────────────────────────────


def _extract_tayda_pn(text: str) -> str:
    if not text or pd.isna(text):
        return ""
    m = re.search(r"[Tt]ayda[:\s]+([A-Za-z]+[-\dA-Za-z]+)", str(text))
    return m.group(1).upper() if m else ""


def _extract_mouser_pn(text: str) -> str:
    if not text or pd.isna(text):
        return ""
    m = re.search(
        r"[Mm]ouser[:\s]+(?:Part\s*No\.?\s*)?([0-9]{3,4}-[A-Za-z0-9\-/]+)",
        str(text),
    )
    return m.group(1) if m else ""


def _extract_package(text: str) -> str:
    if not text or pd.isna(text):
        return ""
    packages = []
    checks = [
        (r"\b0805\b", "0805"),
        (r"\b0603\b", "0603"),
        (r"\b1206\b", "1206"),
        (r"\bSOIC\b", "SOIC"),
        (r"\bSOT-?23\b", "SOT-23"),
        (r"\bSOD-?80\b", "SOD-80"),
        (r"\bDIP\b", "DIP"),
        (r"\bthru[- ]?hole\b", "THT"),
    ]
    for pattern, label in checks:
        if re.search(pattern, text, re.I):
            packages.append(label)
    return ", ".join(packages) if packages else ""


# ── Value Validation ────────────────────────────────────────────────────


def _is_valid_component(val: str) -> bool:
    if not val or pd.isna(val):
        return False
    val = str(val).strip()
    if len(val) < 2:
        return False
    if re.match(r"^\d+\.?\d*$", val):
        return False
    if re.match(r"^[CRUDQLJ]\d+$", val, re.I):
        return False

    noise_patterns = [
        r"^[\(\)\[\]\{\}]+$",
        r"^\d+[vV]$",
        r"^optional",
        r"^\$",
        r"^#\d+$",
        r"^see\s+note",
        r"^n/?a$",
        r"^-+$",
        r"^\*+$",
        r"^install",
        r"^leave\s+",
        r"^do\s+not",
        r"^LEAVE",
        r"^cut\s+to",
        r"^[CRUDQL]\d+-[CRUDQL]?\d+$",
        r"^CAPS$",
        r"^RESISTORS?$",
        r"^\d+\s*x\s*\d+\s*pins?$",
        r"^\d+\s+(and|or)\s+\d+\s*pin",
    ]
    for pattern in noise_patterns:
        if re.match(pattern, val, re.I):
            return False
    return True


# ── Value Normalization ─────────────────────────────────────────────────


def _normalize_value(val: str) -> tuple[str, str]:
    """
    Normalize a component value to standard format.
    Returns (normalized_value, component_type).
    """
    if not val or pd.isna(val):
        return "", "unknown"
    val = str(val).strip()
    if val.lower() in ["-", "nan", "n/a", "", "nothing!"]:
        return "", "skip"
    if not _is_valid_component(val):
        return "", "skip"

    val = val.replace("\r", " ").replace("\n", " ")
    val = re.sub(r"\s+", " ", val).strip()

    # --- RESISTORS ---
    m = re.match(r"^(\d+)\s*([kKmM])\s*(\d+)\s*(?:\(.*\))?\s*$", val)
    if m:
        return f"{m.group(1)}{m.group(2).upper()}{m.group(3)}", "resistor"

    m = re.match(r"^(\d+(?:\.\d+)?)\s*([kKmM])\s*(?:ohm|Ω)?\s*(?:\(.*\))?\s*$", val)
    if m:
        num = m.group(1).rstrip("0").rstrip(".") if "." in m.group(1) else m.group(1)
        return f"{num}{m.group(2).upper()}", "resistor"

    m = re.match(r"^(\d+(?:\.\d+)?)\s*[rRΩ]\s*(?:resistor)?\s*$", val)
    if m:
        return f"{m.group(1)}R", "resistor"

    m = re.match(r"^(\d+(?:\.\d+)?)\s*ohm\s*$", val, re.I)
    if m:
        return f"{m.group(1)}R", "resistor"

    if val.upper() == "RL" or val.lower().startswith("rl "):
        return "RL (LED resistor)", "resistor"

    # --- DIODES (before capacitors to avoid 1N/2N matching as nF) ---
    diode_patterns = [
        (r"1N4148|LL4148", "1N4148"),
        (r"1N400[1-7]", "1N400x"),
        (r"1N5819|B5819", "1N5819"),
        (r"BAT54", "BAT54"),
    ]
    for pattern, repl in diode_patterns:
        if re.search(pattern, val, re.I):
            return repl, "diode"
    if "schottky" in val.lower():
        return "Schottky", "diode"
    if "zener" in val.lower():
        m = re.search(r"(\d+[vV]\d*)", val)
        return (f"Zener {m.group(1).upper()}" if m else "Zener"), "diode"

    # --- TRANSISTORS (before capacitors to avoid 2N matching as nF) ---
    transistor_patterns = [
        (r"^BC[58][0-9]{2}.*", lambda m: m.group(0)[:5].upper()),
        (r"^2N\d{4}.*", lambda m: m.group(0)[:6].upper()),
        (r"^MMBF.*", lambda m: m.group(0).split()[0].upper()),
        (r"^BCM847.*", "BCM847DS"),
        (r"^J\d{3}.*", lambda m: m.group(0).split()[0].upper()),
    ]
    for pattern, repl in transistor_patterns:
        m = re.match(pattern, val, re.I)
        if m:
            return (repl(m) if callable(repl) else repl), "transistor"

    # --- ICs (with "or" alternatives before single-IC patterns) ---
    m = re.match(r"^(TL\d+|LM\d+|NE\d+)\s+or\s+(TL\d+|LM\d+|NE\d+)", val, re.I)
    if m:
        return f"{m.group(1).upper()}/{m.group(2).upper()}", "ic"

    # --- CAPACITORS ---
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([pPnNuUμµ])[fF]?\s*[/\(]?\s*\d*\s*\)?\s*$", val)
    if m:
        unit = m.group(2).lower()
        if unit in ["μ", "µ"]:
            unit = "u"
        return f"{m.group(1)}{unit}F", "capacitor"

    m = re.match(r"^(\d+(?:\.\d+)?)\s*([pPnNuUμµ])\s*$", val)
    if m:
        unit = m.group(2).lower()
        if unit in ["μ", "µ"]:
            unit = "u"
        return f"{m.group(1)}{unit}F", "capacitor"

    m = re.match(r"^(\d+)\s*[uUμµ][fF]?\s*(?:\d+[vV])?\s*(?:electro.*)?\s*$", val, re.I)
    if m:
        return f"{m.group(1)}uF", "capacitor"

    m = re.match(r"^(\d+(?:\.\d+)?)\s*([pPnNuUμµ])[fF]?\s+cap", val, re.I)
    if m:
        unit = m.group(2).lower()
        if unit in ["μ", "µ"]:
            unit = "u"
        return f"{m.group(1)}{unit}F", "capacitor"

    m = re.match(r"^(\d+(?:\.\d+)?)\s*([pPnNuUμµ])[fF]?\s*\(", val)
    if m:
        unit = m.group(2).lower()
        if unit in ["μ", "µ"]:
            unit = "u"
        return f"{m.group(1)}{unit}F", "capacitor"

    # --- ICs ---
    ic_patterns = [
        (r"^TL07[24].*", "TL072/074"),
        (r"^TL08[24].*", "TL082/084"),
        (r"^LM13700.*", "LM13700"),
        (r"^LM358.*", "LM358"),
        (r"^NE555.*|^LM555.*", "555 Timer"),
        (r"^CD40\d+.*", lambda m: m.group(0).split()[0].upper()),
        (r"^74[HhLl][CcSs]\d+.*", lambda m: m.group(0).split()[0].upper()),
        (r"^PT2399.*", "PT2399"),
        (r"^4046.*", "CD4046"),
        (r"^V13700.*", "V13700"),
    ]
    for pattern, repl in ic_patterns:
        m = re.match(pattern, val, re.I)
        if m:
            return (repl(m) if callable(repl) else repl), "ic"

    m = re.match(r"^(TL\d+|LM\d+|NE\d+)\s+or\s+(TL\d+|LM\d+|NE\d+)", val, re.I)
    if m:
        return f"{m.group(1).upper()}/{m.group(2).upper()}", "ic"

    ic_generic = [
        (r"^LM\d{3,4}", lambda m: m.group(0).upper()),
        (r"^4013\b", "CD4013"),
        (r"^4060\b", "CD4060"),
        (r"^555\s*(?:or|/)\s*7555", "555/7555"),
        (r"^SSI\d+", lambda m: m.group(0).upper()),
        (r"^LTC\d+", lambda m: m.group(0).split()[0].upper()),
        (r"^SA571", "SA571"),
    ]
    for pattern, repl in ic_generic:
        m = re.match(pattern, val, re.I)
        if m:
            return (repl(m) if callable(repl) else repl), "ic"

    if re.search(r"[MV]N?3[012]\d{2}", val, re.I):
        m = re.search(r"([MV]N?3[012]\d{2})", val, re.I)
        if m:
            return m.group(1).upper(), "ic"
    if re.search(r"DG[45]\d{2}", val, re.I):
        m = re.search(r"(DG[45]\d{2})", val, re.I)
        if m:
            return m.group(1).upper(), "ic"

    # --- CONNECTORS ---
    if any(k in val.lower() for k in ["3.5mm", "3.5 mm", "kobiconn", "thonkiconn"]):
        if "stereo" in val.lower():
            return "3.5mm Jack Stereo", "connector"
        return "3.5mm Jack Mono", "connector"
    if "eurorack" in val.lower() and "power" in val.lower():
        return "Eurorack Power Header", "connector"
    if "power connector" in val.lower() or "10 pin power" in val.lower():
        return "Eurorack Power Header", "connector"
    if val.lower() in ["jacks", "jack"]:
        return "3.5mm Jack Mono", "connector"
    if "socket" in val.lower() and ("pin" in val.lower() or "ic" in val.lower()):
        return "IC Socket", "connector"

    # --- POTS (trimpot before pot since "trimpot" contains "pot") ---
    if "trimpot" in val.lower() or "trimmer" in val.lower():
        m = re.search(r"(\d+)[kK]", val)
        return (f"{m.group(1)}k Trimpot" if m else "Trimpot"), "pot"
    if "pot" in val.lower():
        m = re.search(r"(\d+)[kK]", val)
        if m:
            taper = "B" if re.search(r"\d+[kK]?[bB]", val) else ""
            return f"{m.group(1)}k{taper} Pot", "pot"
        return "Pot", "pot"

    # --- LEDS ---
    if "led" in val.lower():
        if "bipolar" in val.lower():
            return "Bipolar LED", "led"
        m = re.search(r"(\d+)\s*mm", val.lower())
        return (f"{m.group(1)}mm LED" if m else "LED"), "led"

    # --- MISC ---
    if "vactrol" in val.lower():
        return "Vactrol", "vactrol"
    if "switch" in val.lower() or "toggle" in val.lower():
        if "dpdt" in val.lower():
            return "DPDT Switch", "switch"
        if "spdt" in val.lower():
            return "SPDT Switch", "switch"
        return "Switch", "switch"
    if "78l05" in val.lower() or "7805" in val.lower():
        return "78L05", "regulator"
    if "79l05" in val.lower():
        return "79L05", "regulator"

    # --- Fallback patterns ---
    m = re.match(r"^(\d+)([kKmM])(\d*)\s*[\*\?]?\s*$", val)
    if m:
        suffix = m.group(3) if m.group(3) else ""
        return f"{m.group(1)}{m.group(2).upper()}{suffix}", "resistor"

    m = re.match(r"^(\d+)\s*[rRΩ]\s*[\*\?]+\s*$", val)
    if m:
        return f"{m.group(1)}R", "resistor"

    if re.match(r"^R[Ldv]+$", val, re.I):
        return "RL (LED resistor)", "resistor"
    if val.upper() == "LDR":
        return "LDR", "sensor"

    return val, "other"
