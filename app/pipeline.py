"""
pipeline.py
------------
Wrapper around your GED→CSV converter so it can be imported and called
from a web application.  This version keeps your conversion logic but
turns it into reusable functions instead of a stand-alone desktop script.
"""

import os, re, tempfile, io
import pandas as pd
import numpy as np
from pathlib import Path
from gedcom.parser import Parser
from gedcom.element.individual import IndividualElement


# ---------------------------------------------------------------------
#  Public entry points used by the web app
# ---------------------------------------------------------------------

def load_artifacts(config_path: str | None = None):
    """
    Placeholder to match model-style interface.
    (For a converter there are no heavy artifacts to load.)
    """
    return {"status": "converter ready"}


def convert_ged_to_csv(ged_path: str, output_path: str | None = None) -> pd.DataFrame:
    """
    Convert a GEDCOM file on disk to a cleaned DataFrame.
    Optionally also writes a CSV to `output_path`.
    """
    if not Path(ged_path).is_file():
        raise FileNotFoundError(f"GED file not found: {ged_path}")

    # ------------- Parse GEDCOM -------------
    gedcom_parser = Parser()
    _parse_with_fallback(gedcom_parser, ged_path)
    root_child_elements = gedcom_parser.get_root_child_elements()

    # ------------- Core extraction -------------
    proband = _find_proband(root_child_elements, gedcom_parser)
    ancestry_data = _build_ancestry(proband, gedcom_parser)

    df = _build_dataframe(root_child_elements, gedcom_parser, ancestry_data)

    # Optional cleanups / derived columns
    df = _postprocess_dataframe(df)

    # ------------- Output -------------
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False, encoding="utf-8")

    return df


def convert_bytes_to_csv(content: bytes) -> str:
    """
    Accept uploaded GED bytes, run conversion, and return CSV string.
    Used by Flask / FastAPI routes.
    """
    with tempfile.NamedTemporaryFile(suffix=".ged", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        df = convert_ged_to_csv(tmp_path)
        csv_text = df.to_csv(index=False)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
    return csv_text


# ---------------------------------------------------------------------
#  Internal helpers (trimmed to the essentials from your script)
# ---------------------------------------------------------------------

def _parse_with_fallback(parser: Parser, ged_path: str):
    """Try normal parse; if it fails, re-encode to UTF-8 and retry."""
    try:
        parser.parse_file(ged_path)
    except Exception:
        tmp_norm = _normalize_to_utf8_and_slice_head(ged_path)
        try:
            parser.parse_file(tmp_norm)
        finally:
            try: os.remove(tmp_norm)
            except OSError: pass


def _normalize_to_utf8_and_slice_head(src_path: str) -> str:
    """Return path to temp UTF-8 GED that starts at '0 HEAD'."""
    with open(src_path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        text = raw.decode("utf-16", errors="ignore")
    else:
        if raw.startswith(b"\xef\xbb\xbf"): raw = raw[3:]
        for enc in ("utf-8", "utf-8-sig", "mac_roman", "cp1252", "latin-1"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("latin-1", errors="ignore")

    text = text.lstrip("\ufeff\x00").lstrip()
    m = re.search(r'(?m)^(?:\s*)0\s+HEAD\b', text)
    if not m:
        raise ValueError('GEDCOM header "0 HEAD" not found.')
    text = text[m.start():]
    text = "\r\n".join(text.splitlines()) + "\r\n"
    with tempfile.NamedTemporaryFile("w", suffix=".ged", delete=False,
                                     encoding="utf-8", newline="\r\n") as tf:
        tf.write(text)
        return tf.name


# --------------------------- core data extraction ---------------------------

def _get_name(ind):
    try:
        first, last = ind.get_name()
        return f"{first} {last}".strip()
    except Exception:
        return None


def _get_parents(ind, parser):
    try:
        return parser.get_parents(ind)
    except Exception:
        return []


def _event_date_place(ind_el, parser, primary_tag, alt_tags=()):
    def _first_child_with_tag(el, tag):
        for ch in el.get_child_elements():
            if ch.get_tag() == tag:
                return ch
        return None
    def _child_value(el, tag):
        ch = _first_child_with_tag(el, tag)
        return ch.get_value() if ch else None
    ev = _first_child_with_tag(ind_el, primary_tag)
    if ev:
        date = _child_value(ev, "DATE")
        plac = _child_value(ev, "PLAC")
        if date or plac:
            return date, plac
    for alt in alt_tags:
        ev = _first_child_with_tag(ind_el, alt)
        if ev:
            date = _child_value(ev, "DATE")
            plac = _child_value(ev, "PLAC")
            if date or plac:
                return date, plac
    return None, None


def _find_proband(root_elements, parser):
    """Simplified: pick first Individual if none specified."""
    for el in root_elements:
        if isinstance(el, IndividualElement):
            return el
    raise ValueError("No Individual found in GED file.")


def _build_ancestry(ind, parser, generation=0, lineage_root=None, visited=None, out=None):
    """Recursive ancestry builder."""
    if visited is None: visited = set()
    if out is None: out = {}
    if ind is None: return out
    pid = ind.get_pointer()
    if pid in visited: return out
    visited.add(pid)
    if generation == 3: lineage_root = pid
    out[pid] = {"generations_above_proband": generation,
                "great_grandparent_line": lineage_root}
    for parent in _get_parents(ind, parser):
        _build_ancestry(parent, parser, generation+1, lineage_root, visited, out)
    return out


def _build_dataframe(root_elements, parser, ancestry_data):
    """Recreate your main DataFrame builder (shortened)."""
    rows = []
    for el in root_elements:
        if not isinstance(el, IndividualElement):
            continue
        pid = el.get_pointer()
        nm  = _get_name(el)
        dob, bplace = _event_date_place(el, parser, "BIRT", alt_tags=("CHR", "BAPM", "BAPT"))
        dod, dplace = _event_date_place(el, parser, "DEAT", alt_tags=("BURI", "BUR"))
        parents = _get_parents(el, parser)
        father = mother = None
        for p in parents:
            try:
                if p.get_gender() == 'M': father = _get_name(p)
                elif p.get_gender() == 'F': mother = _get_name(p)
            except Exception: pass
        info = ancestry_data.get(pid, {})
        rows.append({
            "ID": pid,
            "name": nm,
            "DOB": dob,
            "birth_location": bplace,
            "DOD": dod,
            "death_location": dplace,
            "father": father,
            "mother": mother,
            "generations_above_proband": info.get("generations_above_proband"),
            "great_grandparent_line_ptr": info.get("great_grandparent_line")
        })
    return pd.DataFrame(rows)


def _postprocess_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Any extra cleanup or derived columns you already had."""
    # Example: drop completely empty rows, ensure column order
    df = df.dropna(how="all")
    if "name" in df.columns:
        df = df[df["name"].notna()]
    return df.reset_index(drop=True)


















