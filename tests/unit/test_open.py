"""Tests for opening a session."""

from unittest import mock

import pytest

from napalm_lantronix_itmgos import LantronixItmgosDriver


def test_open_passes_netmiko_arguments():
    driver = LantronixItmgosDriver(
        "slc", "admin", "pw", timeout=30, optional_args={"port": 2222, "not_netmiko": 1}
    )
    with mock.patch("napalm.base.base.ConnectHandler") as connect:
        driver.open()
    kwargs = connect.call_args.kwargs
    assert kwargs["device_type"] == "lantronix_itmgos"
    assert kwargs["host"] == "slc"
    assert kwargs["port"] == 2222
    assert kwargs["timeout"] == 30
    assert "not_netmiko" not in kwargs


def test_open_without_netmiko_driver():
    driver = LantronixItmgosDriver("slc", "admin", "pw")
    with (
        mock.patch.dict("napalm_lantronix_itmgos.lantronix_itmgos.CLASS_MAPPER", clear=True),
        pytest.raises(RuntimeError, match="lantronix_itmgos"),
    ):
        driver.open()


def test_export_keeps_yes_values_after_the_preamble():
    driver = LantronixItmgosDriver("slc", "admin", "pw")
    driver.device = mock.Mock()
    driver.device.send_command_timing.return_value = (
        "The configuration will be output.\nDo you want to continue? [no] "
    )
    driver.device.send_command.return_value = "yes\nOne moment while the file is generated...\nset ldap bindpassword\nyes\nyes\nset ldap state enable\n"
    assert driver.get_config()["running"] == "set ldap bindpassword\nyes\nyes\nset ldap state enable\n"
    assert driver.get_config(sanitized=True)["running"] == (
        "set ldap bindpassword\n<secret hidden>\n<secret hidden>\nset ldap state enable\n"
    )
