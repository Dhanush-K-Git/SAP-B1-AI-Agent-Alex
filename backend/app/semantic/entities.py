"""
SAP B1 business entity dictionary — the semantic layer.

Maps friendly business concepts ("sales order", "open invoices", "customer balance")
to the actual SAP B1 tables, key fields, status codes, and join hints. This is injected
into the Claude prompt at runtime so the model writes correct, business-aware SQL instead
of guessing table/column names.

All field names below were verified against the erpref reference (2,546 tables).
Notable SAP B1 quirks captured here:
  - Journal entries (OJDT/JDT1) link via TransId, NOT DocEntry.
  - Account balance is OACT.CurrTotal (there is no OACT.Balance column).
  - The customer/vendor lives on the document HEADER (CardCode), not the lines.
  - CardType on OCRD: 'C' customer, 'S' vendor, 'L' lead.
  - DocStatus: 'O' open, 'C' closed.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Entity:
    name: str                       # canonical key: "sales_order"
    label: str                      # display: "Sales Order"
    domain: str                     # "sales" | "purchase" | "finance" | ...
    header_table: str               # "ORDR"
    line_table: str | None          # "RDR1" (None for masters)
    link_column: str | None         # header↔line join column ("DocEntry"/"TransId")
    date_field: str | None          # "DocDate"
    amount_field: str | None        # "DocTotal"
    status_field: str | None        # "DocStatus"
    partner_field: str | None       # "CardCode"
    partner_type: str | None        # 'C' customer / 'S' vendor  (for OCRD-based filters)
    key_fields: list[str] = field(default_factory=list)
    common_filters: dict[str, str] = field(default_factory=dict)
    synonyms: list[str] = field(default_factory=list)
    notes: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Core entities (curated). ~30 entities spanning the demo domains.
# ─────────────────────────────────────────────────────────────────────────────
ENTITIES: dict[str, Entity] = {
    # ── Sales ────────────────────────────────────────────────────────────────
    "sales_quotation": Entity(
        "sales_quotation", "Sales Quotation", "sales", "OQUT", "QUT1", "DocEntry",
        "DocDate", "DocTotal", "DocStatus", "CardCode", "C",
        key_fields=["DocEntry", "DocNum", "CardCode", "DocDate", "DocTotal"],
        common_filters={"open": "DocStatus = 'O'", "closed": "DocStatus = 'C'"},
        synonyms=["quote", "quotation", "estimate"],
    ),
    "sales_order": Entity(
        "sales_order", "Sales Order", "sales", "ORDR", "RDR1", "DocEntry",
        "DocDate", "DocTotal", "DocStatus", "CardCode", "C",
        key_fields=["DocEntry", "DocNum", "CardCode", "DocDate", "DocDueDate", "DocTotal", "SlpCode"],
        common_filters={"open": "DocStatus = 'O'", "closed": "DocStatus = 'C'",
                        "not_cancelled": "CANCELED = 'N'"},
        synonyms=["order", "sales order", "SO"],
    ),
    "delivery": Entity(
        "delivery", "Delivery / Goods Issue (Sales)", "sales", "ODLN", "DLN1", "DocEntry",
        "DocDate", "DocTotal", "DocStatus", "CardCode", "C",
        key_fields=["DocEntry", "DocNum", "CardCode", "DocDate", "DocTotal"],
        common_filters={"open": "DocStatus = 'O'"},
        synonyms=["delivery note", "shipment", "goods issue"],
    ),
    "ar_invoice": Entity(
        "ar_invoice", "A/R Invoice", "sales", "OINV", "INV1", "DocEntry",
        "DocDate", "DocTotal", "DocStatus", "CardCode", "C",
        key_fields=["DocEntry", "DocNum", "CardCode", "DocDate", "DocDueDate", "DocTotal", "PaidToDate"],
        common_filters={"open": "DocStatus = 'O'", "unpaid": "DocTotal > PaidToDate",
                        "not_cancelled": "CANCELED = 'N'"},
        synonyms=["invoice", "sales invoice", "AR invoice", "customer invoice", "revenue", "sales"],
        notes="Revenue = SUM(DocTotal). Outstanding = SUM(DocTotal - PaidToDate) where DocStatus='O'. "
              "Line items in INV1: ItemCode, Dscription (item name — SAP misspelling), Quantity, Price, LineTotal.",
    ),
    "ar_credit_memo": Entity(
        "ar_credit_memo", "A/R Credit Memo", "sales", "ORIN", "RIN1", "DocEntry",
        "DocDate", "DocTotal", "DocStatus", "CardCode", "C",
        key_fields=["DocEntry", "CardCode", "DocDate", "DocTotal"],
        synonyms=["credit memo", "credit note", "return credit"],
    ),
    "sales_return": Entity(
        "sales_return", "Sales Return", "sales", "ORDN", "RDN1", "DocEntry",
        "DocDate", "DocTotal", "DocStatus", "CardCode", "C",
        key_fields=["DocEntry", "CardCode", "DocDate", "DocTotal"],
        synonyms=["return", "RMA"],
    ),

    # ── Purchase ─────────────────────────────────────────────────────────────
    "purchase_order": Entity(
        "purchase_order", "Purchase Order", "purchase", "OPOR", "POR1", "DocEntry",
        "DocDate", "DocTotal", "DocStatus", "CardCode", "S",
        key_fields=["DocEntry", "DocNum", "CardCode", "DocDate", "DocDueDate", "DocTotal"],
        common_filters={"open": "DocStatus = 'O'"},
        synonyms=["PO", "purchase order"],
    ),
    "goods_receipt_po": Entity(
        "goods_receipt_po", "Goods Receipt PO", "purchase", "OPDN", "PDN1", "DocEntry",
        "DocDate", "DocTotal", "DocStatus", "CardCode", "S",
        key_fields=["DocEntry", "CardCode", "DocDate", "DocTotal"],
        synonyms=["GRPO", "goods receipt"],
    ),
    "ap_invoice": Entity(
        "ap_invoice", "A/P Invoice", "purchase", "OPCH", "PCH1", "DocEntry",
        "DocDate", "DocTotal", "DocStatus", "CardCode", "S",
        key_fields=["DocEntry", "DocNum", "CardCode", "DocDate", "DocDueDate", "DocTotal", "PaidToDate"],
        common_filters={"open": "DocStatus = 'O'", "unpaid": "DocTotal > PaidToDate"},
        synonyms=["AP invoice", "vendor invoice", "supplier invoice", "purchase invoice", "spend"],
        notes="Payables outstanding = SUM(DocTotal - PaidToDate) where DocStatus='O'.",
    ),
    "ap_credit_memo": Entity(
        "ap_credit_memo", "A/P Credit Memo", "purchase", "ORPC", "RPC1", "DocEntry",
        "DocDate", "DocTotal", "DocStatus", "CardCode", "S",
        key_fields=["DocEntry", "CardCode", "DocDate", "DocTotal"],
        synonyms=["vendor credit memo"],
    ),

    # ── Finance ──────────────────────────────────────────────────────────────
    "journal_entry": Entity(
        "journal_entry", "Journal Entry", "finance", "OJDT", "JDT1", "TransId",
        "RefDate", None, None, None, None,
        key_fields=["TransId", "RefDate", "DueDate", "Memo", "TransType"],
        notes="OJDT↔JDT1 join on TransId (NOT DocEntry). Line amounts: JDT1.Debit, JDT1.Credit, "
              "JDT1.Account (G/L account), JDT1.ShortName (BP/account name).",
        synonyms=["journal", "GL posting", "ledger entry"],
    ),
    "incoming_payment": Entity(
        "incoming_payment", "Incoming Payment", "finance", "ORCT", "RCT2", "DocEntry",
        "DocDate", "DocTotal", None, "CardCode", "C",
        key_fields=["DocEntry", "CardCode", "DocDate", "DocTotal", "CashSum", "NoDocSum"],
        synonyms=["customer payment", "receipt", "money received"],
    ),
    "outgoing_payment": Entity(
        "outgoing_payment", "Outgoing Payment", "finance", "OVPM", "VPM1", "DocEntry",
        "DocDate", "DocTotal", None, "CardCode", "S",
        key_fields=["DocEntry", "CardCode", "DocDate", "DocTotal", "CashSum"],
        synonyms=["vendor payment", "supplier payment", "money paid"],
    ),
    "gl_account": Entity(
        "gl_account", "G/L Account (Chart of Accounts)", "finance", "OACT", None, None,
        None, "CurrTotal", None, None, None,
        key_fields=["AcctCode", "AcctName", "CurrTotal", "GroupMask"],
        notes="Account balance = OACT.CurrTotal (there is NO 'Balance' column). "
              "GroupMask groups accounts (assets/liabilities/revenue/expense).",
        synonyms=["account", "chart of accounts", "GL account", "ledger account"],
    ),

    # ── Inventory ────────────────────────────────────────────────────────────
    "item": Entity(
        "item", "Item (Product)", "inventory", "OITM", None, None,
        None, None, None, None, None,
        key_fields=["ItemCode", "ItemName", "ItmsGrpCod", "OnHand", "IsCommited", "OnOrder"],
        notes="OnHand = total stock across warehouses. Available = OnHand - IsCommited.",
        synonyms=["product", "item", "material", "SKU", "stock item"],
    ),
    "item_warehouse_stock": Entity(
        "item_warehouse_stock", "Item Stock by Warehouse", "inventory", "OITW", None, None,
        None, None, None, None, None,
        key_fields=["ItemCode", "WhsCode", "OnHand", "IsCommited", "OnOrder"],
        notes="Per-warehouse stock. Join OITM on ItemCode and OWHS on WhsCode.",
        synonyms=["stock", "inventory level", "warehouse stock", "on hand"],
    ),
    "warehouse": Entity(
        "warehouse", "Warehouse", "inventory", "OWHS", None, None,
        None, None, None, None, None,
        key_fields=["WhsCode", "WhsName"],
        synonyms=["warehouse", "location", "store"],
    ),
    "goods_receipt": Entity(
        "goods_receipt", "Inventory Goods Receipt", "inventory", "OIGN", "IGN1", "DocEntry",
        "DocDate", "DocTotal", "DocStatus", None, None,
        key_fields=["DocEntry", "DocDate", "DocTotal"],
        synonyms=["goods receipt", "stock in"],
    ),
    "goods_issue": Entity(
        "goods_issue", "Inventory Goods Issue", "inventory", "OIGE", "IGE1", "DocEntry",
        "DocDate", "DocTotal", "DocStatus", None, None,
        key_fields=["DocEntry", "DocDate", "DocTotal"],
        synonyms=["goods issue", "stock out"],
    ),
    "stock_transfer": Entity(
        "stock_transfer", "Stock Transfer", "inventory", "OWTR", "WTR1", "DocEntry",
        "DocDate", "DocTotal", "DocStatus", None, None,
        key_fields=["DocEntry", "DocDate"],
        synonyms=["transfer", "stock transfer", "inventory transfer"],
    ),

    # ── Business partners ────────────────────────────────────────────────────
    "customer": Entity(
        "customer", "Customer", "customers", "OCRD", None, None,
        None, "Balance", None, "CardCode", "C",
        key_fields=["CardCode", "CardName", "GroupCode", "Balance", "Country", "City"],
        common_filters={"customers_only": "CardType = 'C'"},
        notes="Filter CardType='C' for customers. OCRD.Balance = current A/R balance.",
        synonyms=["customer", "client", "buyer", "account"],
    ),
    "vendor": Entity(
        "vendor", "Vendor / Supplier", "vendor", "OCRD", None, None,
        None, "Balance", None, "CardCode", "S",
        key_fields=["CardCode", "CardName", "GroupCode", "Balance", "Country", "City"],
        common_filters={"vendors_only": "CardType = 'S'"},
        notes="Filter CardType='S' for vendors. OCRD.Balance = current A/P balance.",
        synonyms=["vendor", "supplier", "seller"],
    ),

    # ── HR ───────────────────────────────────────────────────────────────────
    "employee": Entity(
        "employee", "Employee", "employees", "OHEM", None, None,
        None, None, None, None, None,
        key_fields=["empID", "firstName", "lastName", "dept", "position"],
        notes="Join OUDP on dept for department name.",
        synonyms=["employee", "staff", "worker", "personnel"],
    ),

    # ── Production / MRP ─────────────────────────────────────────────────────
    "production_order": Entity(
        "production_order", "Production Order", "production_mrp", "OWOR", "WOR1", "DocEntry",
        "PostDate", None, "Status", None, None,
        key_fields=["DocEntry", "ItemCode", "PlannedQty", "CmpltQty", "Status", "PostDate"],
        common_filters={"open": "Status = 'R'", "closed": "Status = 'L'"},
        notes="OWOR.Status: 'P' planned, 'R' released, 'L' closed. CmpltQty = completed quantity. "
              "NOTE: this instance has no production data (OWOR is empty).",
        synonyms=["production order", "work order", "manufacturing order"],
    ),
}


def all_entities() -> list[Entity]:
    return list(ENTITIES.values())


def entities_for_tables(table_names: set[str]) -> list[Entity]:
    """Return entities whose header or line table is among the given tables."""
    out: list[Entity] = []
    for ent in ENTITIES.values():
        if ent.header_table in table_names or (ent.line_table and ent.line_table in table_names):
            out.append(ent)
    return out
