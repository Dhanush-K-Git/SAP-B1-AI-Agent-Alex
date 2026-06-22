"""
Smoke-test the SAP B1 service-layer endpoint with a few HANA queries.

Stdlib only (urllib) — run it before installing anything to confirm the endpoint is
reachable and the HANA dialect works from your machine:

    python scripts/check_endpoint.py
    python scripts/check_endpoint.py --url http://vzone.in:1662/api/GetMethod/GetData
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request

_DEFAULT_URL = "http://vzone.in:1662/api/GetMethod/GetData"

_CHECKS: list[tuple[str, str]] = [
    ("connectivity (constant)", 'SELECT 1 AS "ok" FROM DUMMY'),
    ("invoices by status", 'SELECT "DocStatus" AS "status", COUNT(*) AS "cnt" FROM "OINV" GROUP BY "DocStatus"'),
    (
        "top 3 customers by invoice (CAST DOUBLE + MAX-anchored window)",
        'SELECT T1."CardName", CAST(SUM(T0."DocTotal") AS DOUBLE) AS "total" '
        'FROM "OINV" T0 JOIN "OCRD" T1 ON T0."CardCode" = T1."CardCode" '
        'WHERE T0."DocDate" >= ADD_MONTHS((SELECT MAX("DocDate") FROM "OINV"), -12) '
        'GROUP BY T1."CardName" ORDER BY "total" DESC LIMIT 3',
    ),
]


def run(url: str, sql: str) -> tuple[bool, str]:
    full = f"{url}?query={urllib.parse.quote(sql)}"
    try:
        with urllib.request.urlopen(full, timeout=40) as resp:  # noqa: S310 — known endpoint
            body = resp.read().decode("utf-8")
        return True, body
    except urllib.error.HTTPError as exc:
        return False, exc.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=_DEFAULT_URL)
    args = parser.parse_args()

    print(f"Endpoint: {args.url}\n")
    all_ok = True
    for label, sql in _CHECKS:
        ok, body = run(args.url, sql)
        if ok and not body.strip().startswith('{"status"'):
            try:
                preview = json.dumps(json.loads(body))[:300]
            except json.JSONDecodeError:
                preview = body[:300]
            print(f"[PASS] {label}\n       {preview}\n")
        else:
            all_ok = False
            print(f"[FAIL] {label}\n       {body[:300]}\n")

    print("All checks passed ✅" if all_ok else "Some checks failed ❌")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
