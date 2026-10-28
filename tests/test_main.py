from tagbot.__main__ import driver_factory, main
from tagbot.config import Config
from tagbot.driver.fake import FakeGreenScreen


def test_broken_config_stops_with_the_reason(tmp_path, capsys):
    path = tmp_path / "config.toml"
    path.write_text('mode = "live"\n', encoding="utf-8")
    assert main(["--config", str(path), "--no-browser"]) == 2
    assert "mode" in capsys.readouterr().out


def test_demo_mode_never_touches_the_real_green_screen():
    assert isinstance(driver_factory(Config(mode="demo"))(), FakeGreenScreen)
