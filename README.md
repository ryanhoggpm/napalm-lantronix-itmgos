# napalm-lantronix-itmgos

A [NAPALM](https://github.com/napalm-automation/napalm) community driver for Lantronix IT Management Gateway OS, the CLI on the SLC 9000 and SLC 8000 console managers, the EMG 7500 and 8500 edge gateways, and the SLB.

The driver is read-only. It connects over SSH through Netmiko's `lantronix_itmgos` driver and implements getters. It doesn't load, merge, replace or roll back configuration.

## Requirements

- Python 3.10 or later
- NAPALM 5.0 or later
- Netmiko with the `lantronix_itmgos` driver. It's merged on Netmiko's `develop` branch ([ktbyers/netmiko#3909](https://github.com/ktbyers/netmiko/pull/3909)) and will ship in the first release after 4.8.0. Until then, install Netmiko from `develop`.

## Installation

```bash
pip install "netmiko @ git+https://github.com/ktbyers/netmiko.git@develop"
pip install "napalm-lantronix-itmgos @ git+https://github.com/ryanhoggpm/napalm-lantronix-itmgos.git"
```

## Usage

```python
from napalm import get_network_driver

driver = get_network_driver("lantronix_itmgos")
with driver("slc.example.net", "sysadmin", "password") as device:
    print(device.get_facts())
    print(device.get_config(retrieve="running", sanitized=True)["running"])
```

Netmiko options such as `port`, `ssh_config_file` or `use_keys` go in `optional_args`.

## Supported getters

| Getter | Source command |
|---|---|
| `get_facts` | `show sysconfig` |
| `get_interfaces` | `show network port N` |
| `get_interfaces_ip` | `show network port N` |
| `get_interfaces_counters` | `show network port N` |
| `get_snmp_information` | `show snmp` |
| `get_ntp_servers` | `show ntp` |
| `get_users` | `show localusers` |
| `get_config` | `admin config commands copypaste` |
| `cli` | any command |
| `is_alive` | SSH session state |

Interfaces are the Ethernet ports, named `eth1` through `ethN`. Counters the CLI doesn't report, such as octets and broadcast packets, are returned as `-1`.

`get_users` maps local user groups to privilege levels: Administrators are 15, Power Users are 10 and all other users are 1.

## Configuration export

`get_config` returns the running configuration as the CLI commands the device prints for `admin config commands copypaste`. The same commands can be restored with `admin config batch`. There's no separate startup or candidate configuration, so `startup` and `candidate` are always empty.

The export contains secrets in cleartext, including passwords, SNMP communities and pre-shared keys. Use `sanitized=True` to replace them with `<secret hidden>`. Treat unsanitized output, and any Netmiko session log from a `get_config` call, as sensitive.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install "netmiko @ git+https://github.com/ktbyers/netmiko.git@develop"
pip install -e ".[dev]"
pytest
ruff check .
mypy napalm_lantronix_itmgos
```

The tests run NAPALM's standard getter suite against recorded CLI output in `tests/unit/mocked_data`.

## License

Apache License 2.0. See [LICENSE](LICENSE).
