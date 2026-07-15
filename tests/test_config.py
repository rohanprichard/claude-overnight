from datetime import time

from overnight import config, paths


def test_default_config_written_and_parsed():
    cfg = config.load()
    assert paths.config_path().exists()
    assert cfg.window_start == time(1, 0)
    assert cfg.window_end == time(7, 0)
    assert cfg.start_max_utilization == 20
    assert cfg.stop_utilization == 60
    assert cfg.model == "sonnet"


def test_custom_config_overrides():
    paths.ensure_dirs()
    paths.config_path().write_text(
        '[window]\nstart = "23:00"\nend = "06:30"\n'
        '[limits]\nstop_utilization = 45\n'
        '[run]\nmodel = "opus"\njob_timeout_minutes = 5\n'
    )
    cfg = config.load()
    assert cfg.window_start == time(23, 0)
    assert cfg.window_end == time(6, 30)
    assert cfg.stop_utilization == 45
    assert cfg.model == "opus"
    assert cfg.job_timeout_minutes == 5
    # untouched keys keep defaults
    assert cfg.weekly_max_utilization == 80


def test_in_window_normal():
    cfg = config.Config(window_start=time(1, 0), window_end=time(7, 0))
    assert config.in_window(cfg, time(3, 0))
    assert config.in_window(cfg, time(1, 0))
    assert not config.in_window(cfg, time(7, 0))
    assert not config.in_window(cfg, time(12, 0))
    assert not config.in_window(cfg, time(0, 59))


def test_in_window_crossing_midnight():
    cfg = config.Config(window_start=time(23, 0), window_end=time(6, 0))
    assert config.in_window(cfg, time(23, 30))
    assert config.in_window(cfg, time(2, 0))
    assert not config.in_window(cfg, time(12, 0))
    assert not config.in_window(cfg, time(6, 0))
    assert not config.in_window(cfg, time(22, 59))
