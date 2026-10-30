"""Test fixtures."""

import pytest
from napalm.base.test import conftest as parent_conftest
from napalm.base.test.double import BaseTestDouble

from napalm_lantronix_itmgos import lantronix_itmgos

EXPORT_PROMPT = (
    "The configuration will be output (including passwords in cleartext).\nDo you want to continue? [no] "
)


@pytest.fixture(scope="class")
def set_device_parameters(request):
    """Set up the class."""

    def fin():
        request.cls.device.close()

    request.addfinalizer(fin)

    request.cls.driver = lantronix_itmgos.LantronixItmgosDriver
    request.cls.patched_driver = PatchedLantronixItmgosDriver
    request.cls.vendor = "lantronix_itmgos"
    parent_conftest.set_device_parameters(request)


def pytest_generate_tests(metafunc):
    """Generate test cases dynamically."""
    parent_conftest.pytest_generate_tests(metafunc, __file__)


class PatchedLantronixItmgosDriver(lantronix_itmgos.LantronixItmgosDriver):
    """Driver that reads command output from mocked_data instead of a device."""

    def __init__(self, hostname, username, password, timeout=60, optional_args=None):
        super().__init__(hostname, username, password, timeout, optional_args)
        self.patched_attrs = ["device"]
        self.device = FakeLantronixItmgosDevice()

    def open(self):
        pass

    def close(self):
        pass


class FakeLantronixItmgosDevice(BaseTestDouble):
    """Netmiko connection double."""

    def send_command(self, command, **kwargs):
        # The configuration export answers its confirmation prompt with "yes".
        name = "admin config commands copypaste" if command == "yes" else command
        return self.read_txt_file(self.find_file(self.sanitize_text(name) + ".txt"))

    def send_command_timing(self, command, **kwargs):
        return EXPORT_PROMPT

    def is_alive(self):
        return True
