"""Parse CSV / Excel for bulk people import."""
from __future__ import annotations

import csv
import io
from typing import Any


def _norm(h: str) -> str:
    return (h or "").strip().lower().replace(" ", "_").replace("-", "_")


_HEADER_ALIASES: dict[str, str] = {
    "name": "name",
    "full_name": "name",
    "first_name": "name",
    "email": "email",
    "email_address": "email",
    "e_mail": "email",
    "company": "company",
    "organization": "company",
    "org": "company",
    "role": "role",
    "title": "role",
    "job_title": "role",
    "tags": "tags",
}


def _map_row(raw: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in raw.items():
        if k is None:
            continue
        key = _HEADER_ALIASES.get(_norm(str(k)), _norm(str(k)))
        if key in ("name", "email", "company", "role", "tags"):
            out[key] = (str(v) if v is not None else "").strip()
    return out


def parse_csv_bytes(data: bytes) -> list[dict[str, str]]:
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for row in reader:
        m = _map_row(row)
        if m.get("email") and m.get("name"):
            rows.append(m)
    return rows


def parse_xlsx_bytes(data: bytes) -> list[dict[str, str]]:
    try:
        import openpyxl
    except ImportError:
        return []
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    try:
        header_row = next(rows_iter)
    except StopIteration:
        return []
    headers = [_norm(str(h) if h is not None else "") for h in header_row]
    idx_map: dict[str, int] = {}
    for i, h in enumerate(headers):
        canon = _HEADER_ALIASES.get(h, h)
        if canon in ("name", "email", "company", "role", "tags") and canon not in idx_map:
            idx_map[canon] = i
    if "name" not in idx_map or "email" not in idx_map:
        return []
    out = []
    for row in rows_iter:
        if not row:
            continue
        def cell(canon: str) -> str:
            j = idx_map.get(canon)
            if j is None or j >= len(row):
                return ""
            v = row[j]
            return str(v).strip() if v is not None else ""

        name, email = cell("name"), cell("email")
        if email and name:
            out.append(
                {
                    "name": name,
                    "email": email,
                    "company": cell("company"),
                    "role": cell("role"),
                    "tags": cell("tags"),
                }
            )
    return out


def parse_upload(filename: str, data: bytes) -> list[dict[str, str]]:
    fn = (filename or "").lower()
    if fn.endswith(".xlsx"):
        return parse_xlsx_bytes(data)
    return parse_csv_bytes(data)
