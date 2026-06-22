"""
SAP Business One schema conventions.

SAP B1 does NOT declare foreign keys at the database level — relationships live in the
application layer and follow rigid, well-documented naming conventions. This module encodes
those conventions so we can derive PK / FK / join paths from the table+column dictionary
alone, without a live database.

Conventions verified against the shipped erpref reference (2,546 tables):
  - O-prefixed tables          = master / setup / document-header tables   (633 tables)
  - <name>1, <name>2 …         = document line / sub-line tables
  - DocEntry                   = document internal key                     (1,044 tables)
  - DocEntry + LineNum         = composite key of a line table             (837 tables)
  - CardCode -> OCRD           = business-partner reference                (160 tables)
  - ItemCode -> OITM           = item reference                           (344 tables)
  - WhsCode  -> OWHS           = warehouse reference                      (203 tables)
  - AcctCode -> OACT           = G/L account reference                     (69 tables)
"""

from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────────────
# Master tables → their primary-key column.
# These are the anchor tables every other table references.
# ─────────────────────────────────────────────────────────────────────────────
MASTER_PK: dict[str, str] = {
    "OCRD": "CardCode",   # Business Partners (customers + vendors + leads)
    "OITM": "ItemCode",   # Items master
    "OWHS": "WhsCode",    # Warehouses
    "OACT": "AcctCode",   # Chart of Accounts (G/L)
    "OSLP": "SlpCode",    # Sales employees
    "OPRJ": "PrjCode",    # Projects
    "OHEM": "empID",      # Employees (HR)
    "OCRG": "GroupCode",  # Business-partner groups
    "OITB": "ItmsGrpCod", # Item groups
    "OUSR": "USERID",     # Users
    "OCRN": "Currency",   # Currencies
    "OUDG": "Code",       # Posting periods / settings
    "OCST": "Country",    # Countries
    "OUOM": "UomEntry",   # Units of measure
    "OPLN": "ListNum",    # Price lists
    "OFPR": "Code",       # Financial / posting periods
    "ODIM": "DimCode",    # Dimensions
    "OOCR": "OcrCode",    # Cost / profit centers
    "OBTN": "AbsEntry",   # Batch numbers
    "OSRN": "AbsEntry",   # Serial numbers
}

# ─────────────────────────────────────────────────────────────────────────────
# Global foreign-key columns → (referenced master table, referenced PK, confidence).
# Any table containing this column (other than the master itself) references the master.
# ─────────────────────────────────────────────────────────────────────────────
GLOBAL_FK_COLUMNS: dict[str, tuple[str, str, float]] = {
    "CardCode":   ("OCRD", "CardCode",   0.95),
    "ItemCode":   ("OITM", "ItemCode",   0.95),
    "WhsCode":    ("OWHS", "WhsCode",    0.90),
    "FromWhsCod": ("OWHS", "WhsCode",    0.88),
    "WhsC,ode":   ("OWHS", "WhsCode",    0.80),  # known typo guard, harmless if absent
    "AcctCode":   ("OACT", "AcctCode",   0.90),
    "SlpCode":    ("OSLP", "SlpCode",    0.88),
    "PrjCode":    ("OPRJ", "PrjCode",    0.85),
    "Project":    ("OPRJ", "PrjCode",    0.75),
    "empID":      ("OHEM", "empID",      0.85),
    "ItmsGrpCod": ("OITB", "ItmsGrpCod", 0.85),
    "UomEntry":   ("OUOM", "UomEntry",   0.80),
    "ListNum":    ("OPLN", "ListNum",    0.80),
    "OcrCode":    ("OOCR", "OcrCode",    0.78),
    "OcrCode2":   ("OOCR", "OcrCode",    0.75),
    "OcrCode3":   ("OOCR", "OcrCode",    0.75),
}

# GroupCode is ambiguous: BP group (OCRG) on BP-related tables, item group elsewhere.
# Resolved contextually in fk_resolver (only mapped to OCRG when CardCode also present).
AMBIGUOUS_FK_COLUMNS: dict[str, list[tuple[str, str, float]]] = {
    "GroupCode": [
        ("OCRG", "GroupCode", 0.70),   # business-partner group
        ("OITB", "ItmsGrpCod", 0.40),  # item group (lower; usually ItmsGrpCod)
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# Status / enum field value maps — injected into the semantic context so Claude
# knows that "open invoices" means DocStatus = 'O', etc.
# ─────────────────────────────────────────────────────────────────────────────
STATUS_FIELD_VALUES: dict[str, dict[str, str]] = {
    "DocStatus":  {"O": "Open", "C": "Closed", "D": "Draft", "L": "Locked"},
    "LineStatus": {"O": "Open", "C": "Closed"},
    "CANCELED":   {"Y": "Cancelled", "N": "Active"},
    "Canceled":   {"Y": "Cancelled", "N": "Active"},
    "Confirmed":  {"Y": "Confirmed", "N": "Unconfirmed"},
    "CardType":   {"C": "Customer", "S": "Vendor", "L": "Lead"},
    "validFor":   {"Y": "Active", "N": "Inactive"},
    "frozenFor":  {"Y": "Frozen", "N": "Not frozen"},
    "Handwrtten": {"Y": "Manual", "N": "System"},
    "Series":     {},  # numbering series — values are data-dependent
}

# ─────────────────────────────────────────────────────────────────────────────
# Core business domains for the demo. Maps a friendly domain → the SAP B1 tables
# whose columns we embed fully (table + every column) for precise retrieval.
# Everything else is embedded at table level only.
# ─────────────────────────────────────────────────────────────────────────────
CORE_DOMAINS: dict[str, list[str]] = {
    "sales": [
        "OQUT", "QUT1",  # Sales quotations
        "ORDR", "RDR1",  # Sales orders
        "ODLN", "DLN1",  # Deliveries
        "OINV", "INV1",  # A/R invoices
        "ORIN", "RIN1",  # A/R credit memos
        "ORDN", "RDN1",  # Returns
    ],
    "purchase": [
        "OPQT", "PQT1",  # Purchase quotations
        "OPOR", "POR1",  # Purchase orders
        "OPDN", "PDN1",  # Goods receipt PO
        "OPCH", "PCH1",  # A/P invoices
        "ORPC", "RPC1",  # A/P credit memos
        "OPRQ", "PRQ1",  # Purchase requests
    ],
    "finance": [
        "OJDT", "JDT1",  # Journal entries
        "OACT",          # Chart of accounts
        "OVPM", "VPM1",  # Outgoing payments
        "ORCT", "RCT2",  # Incoming payments
        "OFPR",          # Posting periods
    ],
    "inventory": [
        "OITM", "OITW",  # Item master + per-warehouse stock
        "OWHS",          # Warehouses
        "OIGN", "IGN1",  # Goods receipt
        "OIGE", "IGE1",  # Goods issue
        "OWTR", "WTR1",  # Stock transfers
        "OITB",          # Item groups
        "OBTN", "OSRN",  # Batches + serials
    ],
    "vendor": [
        "OCRD",          # Business partners (CardType='S' = vendor)
        "OCRG",          # BP groups
        "OCPR",          # BP contact persons
    ],
    "customers": [
        "OCRD",          # Business partners (CardType='C' = customer)
        "OCRG",
        "OCPR",
    ],
    "employees": [
        "OHEM",          # Employees
        "OUDP",          # Departments
        "OUBR",          # Branches
    ],
    "production_mrp": [
        "OWOR", "WOR1",  # Production orders
        "OITT", "ITT1",  # Bill of materials
        "ORCP", "RCP1",  # Recommendations (MRP)
    ],
}


def all_core_tables() -> set[str]:
    """Flat set of every table whose columns get fully embedded."""
    tables: set[str] = set()
    for group in CORE_DOMAINS.values():
        tables.update(group)
    return tables


def is_master(table_name: str) -> bool:
    """O-prefixed tables are SAP B1 master / header tables."""
    return len(table_name) >= 2 and table_name[0] == "O" and table_name[1].isupper()


def header_twin(line_table: str) -> str | None:
    """
    Given a candidate line table (e.g. 'RDR1'), return its document-header twin
    ('ORDR') by stripping trailing digits and prepending 'O'. Caller checks existence.

        RDR1 -> ORDR    INV1 -> OINV    POR1 -> OPOR    DLN1 -> ODLN
    """
    base = line_table.rstrip("0123456789")
    if not base or base == line_table:
        return None  # no trailing digit → not a line table
    return "O" + base
