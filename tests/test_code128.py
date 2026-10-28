import pytest

from tagbot.code128 import PATTERNS, code128_values, modules, svg


def test_symbol_values_include_start_b_checksum_and_stop():
    assert code128_values("MC-A2") == [104, 45, 35, 13, 33, 18, 68, 106]


def test_every_symbol_is_eleven_modules_wide_and_stop_is_thirteen():
    assert len(PATTERNS) == 107
    assert all(len(p) == 6 and sum(map(int, p)) == 11 for p in PATTERNS[:106])
    assert sum(map(int, PATTERNS[106])) == 13


def test_module_sequence_starts_with_start_b_bars_and_has_quiet_zones():
    bars = modules("MC-A2", quiet=10)
    assert bars[:10] == "0" * 10 and bars[-10:] == "0" * 10
    # Start B = 2 1 1 2 1 4 (bar space bar space bar space)
    assert bars[10:21] == "11" + "0" + "1" + "00" + "1" + "0000"
    assert len(bars) == 10 + 11 * 7 + 13 + 10


def test_characters_outside_code_set_b_are_refused():
    with pytest.raises(ValueError):
        code128_values("ชมพู")


def test_svg_draws_one_rect_per_bar_run():
    drawing = svg("NUM-1")
    assert drawing.startswith("<svg")
    bar_runs = [run for run in modules("NUM-1", quiet=10).split("0") if run]
    assert drawing.count("<rect") == len(bar_runs)


@pytest.mark.parametrize("text", ["MC-A2", "CT-M04", "EMP-T0001", "CMD-FULL", "CMD-UNDO", "NUM-7", "DIE.4", "WD01"])
def test_rendered_barcode_is_read_back_by_a_real_decoder(text):
    zxingcpp = pytest.importorskip("zxingcpp")
    image_module = pytest.importorskip("PIL.Image")
    bars = modules(text, quiet=12)
    scale, height = 3, 80
    image = image_module.new("L", (len(bars) * scale, height), 255)
    for index, bar in enumerate(bars):
        if bar == "1":
            for x in range(index * scale, (index + 1) * scale):
                for y in range(height):
                    image.putpixel((x, y), 0)
    [result] = zxingcpp.read_barcodes(image)
    assert (result.text, result.format.name) == (text, "Code128")
