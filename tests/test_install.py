from overnight import install


def test_systemd_units_reference_runner_and_logs():
    service, timer = install.systemd_units()
    assert "ExecStart=" in service
    assert "run" in service
    assert "runner.log" in service
    assert "OnCalendar=*:0/30" in timer
    assert "Persistent=true" in timer


def test_systemd_service_bakes_path():
    service, _ = install.systemd_units()
    assert "Environment=PATH=" in service


def test_runner_command_is_nonempty():
    cmd = install._runner_command()
    assert cmd[-1] == "run"
