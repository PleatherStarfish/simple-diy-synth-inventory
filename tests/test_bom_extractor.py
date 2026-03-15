import csv
import sys
from types import SimpleNamespace
from pathlib import Path

import pandas as pd
import pytest

from eurorack_inventory.services.bom_extractor import (
    _unpack_variant_table,
    clean_module_name,
    extract_pdf,
    extract_csv,
    file_hash,
)


class TestCleanModuleName:
    def test_strips_nlc_prefix(self):
        assert clean_module_name("NLC - 4seq") == "4seq"
        assert clean_module_name("NLC-Sloth") == "Sloth"

    def test_strips_bom_suffix(self):
        assert clean_module_name("Sloth_BOM") == "Sloth"
        assert clean_module_name("Sloth_build_and_bom") == "Sloth"
        assert clean_module_name("Neuron Build and BOM") == "Neuron"

    def test_cleans_underscores_and_spaces(self):
        assert clean_module_name("Dual_Neuron") == "Dual Neuron"
        assert clean_module_name("Sloth  BOM") == "Sloth"

    def test_url_decode(self):
        assert clean_module_name("Sloth+Module") == "Sloth Module"

    def test_empty(self):
        assert clean_module_name("") == ""


class TestFileHash:
    def test_computes_hash(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        h = file_hash(f)
        assert len(h) == 64  # SHA-256 hex
        assert h == file_hash(f)  # deterministic

    def test_different_content_different_hash(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("hello")
        f2.write_text("world")
        assert file_hash(f1) != file_hash(f2)


class TestExtractCSV:
    def _write_csv(self, path: Path, rows: list[dict]):
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

    def test_combined_csv_multiple_modules(self, tmp_path):
        csv_path = tmp_path / "combined.csv"
        self._write_csv(csv_path, [
            {"_module": "Sloth", "_source_file": "Sloth.pdf", "VALUE": "100K", "QUANTITY": "5", "DETAILS": ""},
            {"_module": "Sloth", "_source_file": "Sloth.pdf", "VALUE": "TL072", "QUANTITY": "2", "DETAILS": "IC"},
            {"_module": "Neuron", "_source_file": "Neuron.pdf", "VALUE": "10K", "QUANTITY": "3", "DETAILS": ""},
        ])
        result = extract_csv(csv_path)
        assert len(result) == 2
        assert "Sloth" in result
        assert "Neuron" in result
        assert len(result["Sloth"]) == 2
        assert len(result["Neuron"]) == 1
        assert result["Sloth"][0].raw_description == "100K"
        assert result["Sloth"][0].raw_qty == "5"
        assert result["Neuron"][0].raw_description == "10K"

    def test_single_module_csv_no_module_column(self, tmp_path):
        csv_path = tmp_path / "Sloth.csv"
        self._write_csv(csv_path, [
            {"VALUE": "100K", "QUANTITY": "2", "DETAILS": "0805"},
            {"VALUE": "TL072", "QUANTITY": "1", "DETAILS": ""},
        ])
        result = extract_csv(csv_path)
        assert len(result) == 1
        assert "Sloth" in result
        assert len(result["Sloth"]) == 2

    def test_empty_values_skipped(self, tmp_path):
        csv_path = tmp_path / "test.csv"
        self._write_csv(csv_path, [
            {"_module": "Sloth", "VALUE": "100K", "QUANTITY": "1", "DETAILS": ""},
            {"_module": "Sloth", "VALUE": "", "QUANTITY": "", "DETAILS": ""},
        ])
        result = extract_csv(csv_path)
        assert len(result["Sloth"]) == 1

    def test_line_numbers_sequential(self, tmp_path):
        csv_path = tmp_path / "test.csv"
        self._write_csv(csv_path, [
            {"_module": "Sloth", "VALUE": "A", "QUANTITY": "1", "DETAILS": ""},
            {"_module": "Sloth", "VALUE": "B", "QUANTITY": "2", "DETAILS": ""},
            {"_module": "Sloth", "VALUE": "C", "QUANTITY": "3", "DETAILS": ""},
        ])
        result = extract_csv(csv_path)
        items = result["Sloth"]
        assert [i.line_number for i in items] == [1, 2, 3]

    def test_module_name_cleaned(self, tmp_path):
        csv_path = tmp_path / "test.csv"
        self._write_csv(csv_path, [
            {"_module": "NLC - Sloth_build_and_bom", "VALUE": "100K", "QUANTITY": "1", "DETAILS": ""},
        ])
        result = extract_csv(csv_path)
        assert "Sloth" in result

    def test_notes_preserved(self, tmp_path):
        csv_path = tmp_path / "test.csv"
        self._write_csv(csv_path, [
            {"_module": "Sloth", "VALUE": "TL072", "QUANTITY": "2", "DETAILS": "Tayda: A-1136"},
        ])
        result = extract_csv(csv_path)
        assert result["Sloth"][0].raw_notes == "Tayda: A-1136"


class TestExtractPdf:
    def test_extract_pdf_accepts_uppercase_standard_columns(self, tmp_path, monkeypatch):
        pdf_path = tmp_path / "test.pdf"
        pdf_path.write_text("fake pdf")

        uppercase_table = pd.DataFrame(
            {
                "VALUE": ["100n", "TL072"],
                "QUANTITY": ["3", "1"],
                "DETAILS": ["0805", "SOIC"],
            }
        )

        monkeypatch.setitem(sys.modules, "tabula", SimpleNamespace())
        monkeypatch.setattr(
            "eurorack_inventory.services.bom_extractor._extract_tables_from_pdf",
            lambda *_args, **_kwargs: [uppercase_table],
        )
        monkeypatch.setattr(
            "eurorack_inventory.services.bom_extractor._clean_bom_dataframe_with_reason",
            lambda df, min_cols=2, min_rows=3: (df, ""),
        )
        monkeypatch.setattr(
            "eurorack_inventory.services.bom_extractor._normalize_bom_table_with_reason",
            lambda df: (df, ""),
        )

        result = extract_pdf(pdf_path)

        assert len(result) == 2
        assert result[0].raw_description == "100n"
        assert result[0].raw_qty == "3"
        assert result[1].raw_description == "TL072"

    def test_unpack_variant_table_handles_float_designators(self):
        df = pd.DataFrame(
            {
                0: [float("nan"), "R1", "R2"],
                "torpor": ["100K", "220K", "330K"],
                "apathy": ["", "", ""],
                "inertia": ["", "", ""],
            }
        )

        result = _unpack_variant_table(df)

        assert not result.empty
        assert set(result.columns) == {"VALUE", "QUANTITY", "DETAILS"}
        assert any("220K" in row["VALUE"] for row in result.to_dict(orient="records"))
