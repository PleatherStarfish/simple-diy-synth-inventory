import pytest

from eurorack_inventory.domain.models import NormalizedBomItem, RawBomItem
from eurorack_inventory.services.bom_normalizer import normalize, _normalize_value, _clean_quantity, _extract_tayda_pn, _extract_mouser_pn, _extract_package, _is_valid_component


def _raw(desc: str, qty: str = "1", notes: str | None = None) -> RawBomItem:
    return RawBomItem(
        id=1, bom_source_id=1, line_number=1,
        raw_description=desc, raw_qty=qty, raw_notes=notes,
    )


class TestNormalizeValue:
    # --- Resistors ---
    @pytest.mark.parametrize("input_val,expected", [
        ("100k", "100K"),
        ("100K", "100K"),
        ("4k7", "4K7"),
        ("4K7", "4K7"),
        ("470R", "470R"),
        ("470r", "470R"),
        ("100ohm", "100R"),
        ("10R", "10R"),
        ("1M", "1M"),
        ("2M2", "2M2"),
    ])
    def test_resistors(self, input_val, expected):
        norm, comp_type = _normalize_value(input_val)
        assert norm == expected
        assert comp_type == "resistor"

    # --- Capacitors ---
    @pytest.mark.parametrize("input_val,expected", [
        ("100nF", "100nF"),
        ("100n", "100nF"),
        ("47p", "47pF"),
        ("1u", "1uF"),
        ("10uF", "10uF"),
        ("100nF (104)", "100nF"),
        ("10uF 25V", "10uF"),
    ])
    def test_capacitors(self, input_val, expected):
        norm, comp_type = _normalize_value(input_val)
        assert norm == expected
        assert comp_type == "capacitor"

    # --- ICs ---
    @pytest.mark.parametrize("input_val,expected", [
        ("TL072", "TL072/074"),
        ("TL074", "TL072/074"),
        ("LM13700", "LM13700"),
        ("PT2399", "PT2399"),
        ("CD4013", "CD4013"),
        ("CD40106", "CD40106"),
        ("TL072 or TL082", "TL072/TL082"),
    ])
    def test_ics(self, input_val, expected):
        norm, comp_type = _normalize_value(input_val)
        assert norm == expected
        assert comp_type == "ic"

    # --- Transistors ---
    @pytest.mark.parametrize("input_val,expected", [
        ("BC547", "BC547"),
        ("BC857", "BC857"),
        ("2N3904", "2N3904"),
    ])
    def test_transistors(self, input_val, expected):
        norm, comp_type = _normalize_value(input_val)
        assert norm == expected
        assert comp_type == "transistor"

    # --- Diodes ---
    @pytest.mark.parametrize("input_val,expected", [
        ("1N4148", "1N4148"),
        ("LL4148", "1N4148"),
        ("1N5819", "1N5819"),
    ])
    def test_diodes(self, input_val, expected):
        norm, comp_type = _normalize_value(input_val)
        assert norm == expected
        assert comp_type == "diode"

    # --- Connectors ---
    def test_jack(self):
        norm, comp_type = _normalize_value("3.5mm jack")
        assert comp_type == "connector"
        assert "3.5mm" in norm

    def test_thonkiconn(self):
        norm, comp_type = _normalize_value("thonkiconn")
        assert comp_type == "connector"

    # --- Pots ---
    def test_pot(self):
        norm, comp_type = _normalize_value("100k pot")
        assert norm == "100k Pot"
        assert comp_type == "pot"

    def test_trimpot(self):
        norm, comp_type = _normalize_value("10k trimpot")
        assert norm == "10k Trimpot"
        assert comp_type == "pot"

    # --- Skip patterns ---
    @pytest.mark.parametrize("input_val", [
        "", "-", "nan", "n/a", "nothing!",
        "C1", "R5", "U3",  # designators
        "25V",  # just voltage
        "optional",
        "CAPS", "RESISTORS",
    ])
    def test_skip_values(self, input_val):
        norm, comp_type = _normalize_value(input_val)
        assert comp_type == "skip" or norm == ""


class TestCleanQuantity:
    @pytest.mark.parametrize("input_val,expected", [
        ("5", 5),
        ("5.0", 5),
        ("2x3", 6),
        ("", 1),
        ("abc", 1),
        ("0", 1),
    ])
    def test_quantities(self, input_val, expected):
        assert _clean_quantity(input_val) == expected


class TestExtractPartNumbers:
    def test_tayda(self):
        assert _extract_tayda_pn("Tayda: A-1136") == "A-1136"
        assert _extract_tayda_pn("tayda A-5781") == "A-5781"
        assert _extract_tayda_pn("no part number") == ""

    def test_mouser(self):
        assert _extract_mouser_pn("Mouser: 595-TL072CP") == "595-TL072CP"
        assert _extract_mouser_pn("Mouser Part No 926-LM13700MX") == "926-LM13700MX"
        assert _extract_mouser_pn("no part number") == ""


class TestExtractPackage:
    def test_packages(self):
        assert "0805" in _extract_package("0805 SMD")
        assert "SOIC" in _extract_package("SOIC-8")
        assert "DIP" in _extract_package("DIP-8")
        assert "THT" in _extract_package("thru-hole")
        assert _extract_package("") == ""


class TestNormalizePipeline:
    def test_full_pipeline(self):
        raw_items = [
            _raw("100K", "5", "Tayda: A-1234"),
            _raw("TL072", "2"),
            _raw("", "1"),  # empty, should be skipped
            _raw("C1", "1"),  # designator, should be skipped
            _raw("1N4148", "10"),
        ]
        result = normalize(raw_items)
        assert len(result) == 3

        resistor = next(r for r in result if r.component_type == "resistor")
        assert resistor.normalized_value == "100K"
        assert resistor.qty == 5
        assert resistor.tayda_pn == "A-1234"

        ic = next(r for r in result if r.component_type == "ic")
        assert ic.normalized_value == "TL072/074"

        diode = next(r for r in result if r.component_type == "diode")
        assert diode.normalized_value == "1N4148"
        assert diode.qty == 10

    def test_preserves_bom_source_id(self):
        raw = RawBomItem(
            id=42, bom_source_id=7, line_number=1,
            raw_description="100K", raw_qty="1",
        )
        result = normalize([raw])
        assert result[0].bom_source_id == 7
        assert result[0].raw_item_id == 42
