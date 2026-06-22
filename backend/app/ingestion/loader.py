"""
Load and normalize the erpref SAP B1 reference JSON into typed dataclasses.

Input shape (per table):
    {
      "table_name": "OINV", "module": "Marketing Documents", "module_id": 5,
      "description": "A/R Invoice", "total_columns": 200,
      "columns": [
        {"column_number": 1, "field": "DocEntry", "description": "Internal Number",
         "type": "Int", "length": 11}, ...
      ]
    }
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class Column:
    number: int
    field: str
    description: str
    type: str
    length: int


@dataclass(slots=True)
class Table:
    name: str
    module: str
    module_id: int
    description: str
    columns: list[Column] = field(default_factory=list)

    def column_names(self) -> set[str]:
        return {c.field for c in self.columns}

    def has_column(self, name: str) -> bool:
        return any(c.field == name for c in self.columns)

    def get_column(self, name: str) -> Column | None:
        for c in self.columns:
            if c.field == name:
                return c
        return None


@dataclass(slots=True)
class Catalog:
    tables: dict[str, Table]

    def names(self) -> set[str]:
        return set(self.tables.keys())

    def exists(self, name: str) -> bool:
        return name in self.tables

    def __len__(self) -> int:
        return len(self.tables)


def load_catalog(json_path: str | Path) -> Catalog:
    """Parse the erpref JSON file into a Catalog of typed Tables."""
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"erpref JSON not found: {path}")

    with path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)

    if not isinstance(raw, list):
        raise ValueError("Expected a top-level JSON array of table objects")

    tables: dict[str, Table] = {}
    for entry in raw:
        name = entry["table_name"]
        cols = [
            Column(
                number=int(c.get("column_number", 0)),
                field=str(c["field"]),
                description=str(c.get("description", "")).strip(),
                type=str(c.get("type", "")).strip(),
                length=int(c.get("length", 0) or 0),
            )
            for c in entry.get("columns", [])
        ]
        tables[name] = Table(
            name=name,
            module=str(entry.get("module", "")).strip(),
            module_id=int(entry.get("module_id", 0) or 0),
            description=str(entry.get("description", "")).strip(),
            columns=cols,
        )

    return Catalog(tables=tables)
