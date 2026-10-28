import pytest

from tagbot.config import ConfigError, load_config


def write(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_values_in_file_override_defaults_and_the_rest_stay_default(tmp_path):
    cfg = load_config(write(tmp_path, 'mode = "pcomm"\nsession = "B"\n[options]\nconfirm_before_final_enter = false\n'))
    assert cfg.mode == "pcomm"
    assert cfg.session == "B"
    assert cfg.options.confirm_before_final_enter is False
    assert cfg.options.lot_qty_includes_ng is True
    assert cfg.shifts == {"A": "08:00", "B": "16:00", "C": "00:00"}


def test_data_dir_is_resolved_next_to_the_config_file(tmp_path):
    cfg = load_config(write(tmp_path, 'data_dir = "mydata"\n'))
    assert cfg.data_dir == tmp_path / "mydata"


def test_misspelled_key_is_rejected_instead_of_silently_ignored(tmp_path):
    with pytest.raises(ConfigError, match="sesion"):
        load_config(write(tmp_path, 'sesion = "A"\n'))


def test_unknown_mode_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="mode"):
        load_config(write(tmp_path, 'mode = "real"\n'))


def test_bad_shift_time_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="25:00"):
        load_config(write(tmp_path, '[shifts]\nA = "25:00"\n'))


def test_broken_barcode_pattern_is_rejected(tmp_path):
    with pytest.raises(ConfigError, match="mat_coil"):
        load_config(write(tmp_path, "[barcodes]\nmat_coil = '^OF[0-9'\n"))


def test_config_saved_with_utf8_bom_by_notepad_is_read(tmp_path):
    path = tmp_path / "config.toml"
    path.write_bytes('﻿mode = "pcomm"\ncolors = ["ชมพู"]\n'.encode("utf-8"))
    cfg = load_config(path)
    assert (cfg.mode, cfg.colors) == ("pcomm", ["ชมพู"])
