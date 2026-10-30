"""NAPALM driver for Lantronix IT Management Gateway OS.

IT Management Gateway OS is the CLI shared by the SLC 9000 and SLC 8000 console
managers, the EMG 7500/8500 edge gateways and the SLB. The driver is read-only: it
implements getters over SSH through the Netmiko ``lantronix_itmgos`` driver and does
not load, merge or replace configuration.
"""

import ipaddress
import re
from typing import Any

from napalm.base import NetworkDriver, models
from napalm.base.exceptions import ConnectionClosedException
from napalm.base.netmiko_helpers import netmiko_args
from netmiko.ssh_dispatcher import CLASS_MAPPER

PROMPT_PATTERN = r"\[[\w.\-]{1,64}\]>\s?$"

# A "Key: value" pair. Keys never contain two spaces in a row, which is how a value
# padded out to the next column is told apart from the next key.
_KEY = r"[A-Za-z][^:\s]*(?: [^:\s]+)*"
_PAIR = re.compile(rf"^\s*({_KEY}):(?:\s+(.*?))?\s*$")
_SPLIT = re.compile(rf"^(.*?\S)\s{{2,}}({_KEY}:(?:\s.*)?)$")

_EMPTY = ("[none]", "<none>", "none", "")

# Lines the configuration export prints around the commands themselves.
_EXPORT_NOISE = re.compile(
    r"^(The configuration will be output.*|Do you want to continue\? \[no\].*|yes|"
    r"One moment while the file is generated.*)$"
)

# A prompted secret is exported as the command, then the value and its confirmation on
# the next two lines: "set tacacs+ secret", "admin ftp password" and so on.
_PROMPTED_SECRET = re.compile(
    r"^((?:set|admin) (?:[^\n]*(?:password|phrase|secret|key)|"
    r"site (?:dialoutpassword|chapsecret) [^\n]+)\n)[^\n]*\n[^\n]*\n",
    re.MULTILINE,
)
_COMMUNITY = re.compile(r"\b((?:ro|rw|trap)community) (?:'[^'\n]*'|\"[^\"\n]*\"|\S+)")
_TRAP_ACTION_COMMUNITY = re.compile(r"(\saction snmptrap\b[^\n]*?\scommunity) (?:'[^'\n]*'|\"[^\"\n]*\"|\S+)")
_LOCALUSER_HASH = re.compile(r"^(set localusers password \S+ enc) \S+", re.MULTILINE)

# Local user groups as abbreviated in "show localusers", mapped to NAPALM levels.
_GROUP_LEVELS = {"adm": 15, "pwr": 10}


def _pairs(text: str) -> list[tuple[str, str]]:
    """Return the "Key: value" pairs of CLI output, left column before right column."""
    pairs = []
    for line in text.splitlines():
        line = line.rstrip()
        if not line.strip():
            continue
        parts = []
        rest = line
        while True:
            m = _SPLIT.match(rest)
            if not m:
                parts.append(rest)
                break
            parts.append(m.group(1))
            rest = m.group(2)
        for part in parts:
            m = _PAIR.match(part)
            if m:
                pairs.append((m.group(1).strip(), (m.group(2) or "").strip()))
    return pairs


def _sections(text: str) -> dict[str, dict[str, str]]:
    """Split "show sysconfig" into its titled sections of first-seen "Key: value" pairs."""
    lines = text.splitlines()
    sections: dict[str, list[str]] = {"": []}
    current = ""
    for i, line in enumerate(lines):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if line.strip() and re.fullmatch(r"-{4,}", nxt.strip()):
            current = line.strip()
            sections.setdefault(current, [])
            continue
        if re.fullmatch(r"-{4,}", line.strip()):
            continue
        sections[current].append(line)
    parsed = {}
    for title, body in sections.items():
        values: dict[str, str] = {}
        for key, value in _pairs("\n".join(body)):
            values.setdefault(key, value)
        parsed[title] = values
    return parsed


def _value(value: str | None) -> str:
    """Return a CLI value, or an empty string for the CLI's placeholders for no value."""
    if value is None or value.strip().lower() in _EMPTY:
        return ""
    return value.strip()


def _uptime_seconds(text: str) -> float:
    """Convert "1 day, 5 hours, 19 minutes" to seconds."""
    units = {"day": 86400, "hour": 3600, "minute": 60, "second": 1}
    total = 0
    for amount, unit in re.findall(r"(\d+)\s+(day|hour|minute|second)s?", text):
        total += int(amount) * units[unit]
    return float(total)


def _int(value: str | None) -> int:
    try:
        return int(_value(value))
    except ValueError:
        return -1


def sanitize_config(config: str) -> str:
    """Hide passwords, keys, secrets and SNMP communities in a configuration export."""
    config = _PROMPTED_SECRET.sub(lambda m: f"{m.group(1)}<secret hidden>\n<secret hidden>\n", config)
    config = _COMMUNITY.sub(r"\1 '<secret hidden>'", config)
    config = _TRAP_ACTION_COMMUNITY.sub(r"\1 <secret hidden>", config)
    return _LOCALUSER_HASH.sub(r"\1 <secret hidden>", config)


class LantronixItmgosDriver(NetworkDriver):
    """NAPALM driver for Lantronix IT Management Gateway OS."""

    def __init__(
        self,
        hostname: str,
        username: str,
        password: str,
        timeout: int = 60,
        optional_args: dict[str, Any] | None = None,
    ) -> None:
        """Store connection parameters. Netmiko options pass through optional_args."""
        self.hostname = hostname
        self.username = username
        self.password = password
        self.timeout = timeout
        self.optional_args = optional_args or {}
        self.netmiko_optional_args = netmiko_args(self.optional_args)
        self.device: Any = None
        self.platform = "lantronix_itmgos"

    def open(self) -> None:
        """Open an SSH session through Netmiko."""
        if "lantronix_itmgos" not in CLASS_MAPPER:
            raise RuntimeError(
                "The installed Netmiko has no lantronix_itmgos driver; it needs a release after 4.8.0 "
                "or Netmiko from the develop branch"
            )
        self.device = self._netmiko_open("lantronix_itmgos", netmiko_optional_args=self.netmiko_optional_args)

    def close(self) -> None:
        """Close the SSH session."""
        self._netmiko_close()

    def _send_command(self, command: str) -> str:
        if self.device is None:
            raise ConnectionClosedException("Connection is not open")
        return self.device.send_command(command, read_timeout=self.timeout)

    def is_alive(self) -> models.AliveDict:
        """Report whether the SSH session is still usable."""
        if self.device is None:
            return {"is_alive": False}
        try:
            return {"is_alive": bool(self.device.is_alive())}
        except (OSError, EOFError):
            return {"is_alive": False}

    def cli(self, commands: list[str], encoding: str = "text") -> dict[str, Any]:
        """Run CLI commands and return their output keyed by command."""
        if encoding != "text":
            raise NotImplementedError(f"{encoding} is not a supported encoding")
        return {command: self._send_command(command) for command in commands}

    def _sysconfig(self) -> dict[str, dict[str, str]]:
        return _sections(self._send_command("show sysconfig"))

    @staticmethod
    def _ports(sysconfig: dict[str, dict[str, str]]) -> list[int]:
        hardware = sysconfig.get("Hardware/Firmware Information", {})
        ports = {int(m.group(1)) for key in hardware for m in [re.match(r"Eth(\d+) HW Address$", key)] if m}
        return sorted(ports)

    def get_facts(self) -> models.FactsDict:
        """Return model, firmware, serial number, uptime, hostname and Ethernet ports."""
        sysconfig = self._sysconfig()
        hardware = sysconfig.get("Hardware/Firmware Information", {})
        names = sysconfig.get("Hostname and Name Server Settings", {})
        hostname = _value(names.get("Hostname"))
        domain = _value(names.get("Domain"))
        return {
            "uptime": _uptime_seconds(sysconfig.get("", {}).get("Uptime", "")),
            "vendor": "Lantronix",
            "os_version": _value(hardware.get("Firmware Version")),
            "serial_number": _value(hardware.get("S/N")),
            "model": _value(hardware.get("Model")),
            "hostname": hostname,
            "fqdn": f"{hostname}.{domain}" if hostname and domain else hostname,
            "interface_list": [f"eth{n}" for n in self._ports(sysconfig)],
        }

    def _network_ports(self) -> dict[int, tuple[str, str]]:
        """Return each Ethernet port's state from sysconfig and its "show network port" output."""
        sysconfig = self._sysconfig()
        network = sysconfig.get("Network Settings", {})
        ports = {}
        for n in self._ports(sysconfig):
            state = network.get(f"Eth{n}") or network.get(f"Eth{n} (SFP)") or ""
            ports[n] = (state, self._send_command(f"show network port {n}"))
        return ports

    def get_interfaces(self) -> dict[str, models.InterfaceDict]:
        """Return link state, speed, MTU and MAC address of each Ethernet port."""
        interfaces = {}
        for n, (state, output) in self._network_ports().items():
            values = dict(_pairs(output))
            speed = re.search(r"Speed:\s*(\d+)\s*Mb/s", output)
            interfaces[f"eth{n}"] = {
                "is_up": _value(values.get("Link State")).lower() == "up",
                "is_enabled": not state.lower().startswith("disable"),
                "description": "",
                "last_flapped": -1.0,
                "speed": float(speed.group(1)) if speed else 0.0,
                "mtu": max(_int(values.get("MTU")), 0),
                "mac_address": _value(values.get("HW Address")).upper(),
            }
        return interfaces

    def get_interfaces_ip(self) -> dict[str, Any]:
        """Return the IPv4 and IPv6 addresses of each Ethernet port."""
        result: dict[str, Any] = {}
        for n, (_, output) in self._network_ports().items():
            pairs = _pairs(output)
            values = dict(pairs)
            entry: dict[str, dict[str, dict[str, int]]] = {}
            address, mask = _value(values.get("IP Address")), _value(values.get("Subnet Mask"))
            if address and mask:
                prefix = ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen
                entry["ipv4"] = {address: {"prefix_length": prefix}}
            for key, value in pairs:
                m = re.match(r"([0-9a-fA-F:]+)/(\d+)", _value(value)) if key == "IPv6 Address" else None
                if m:
                    entry.setdefault("ipv6", {})[m.group(1)] = {"prefix_length": int(m.group(2))}
            if entry:
                result[f"eth{n}"] = entry
        return result

    def get_interfaces_counters(self) -> dict[str, models.InterfaceCounterDict]:
        """Return byte, packet, error and multicast counters of each Ethernet port.

        The CLI doesn't report discards, broadcasts or transmitted multicast; those are -1.
        """
        counters = {}
        for n, (_, output) in self._network_ports().items():
            values = dict(_pairs(output))
            rx_packets, tx_packets = _int(values.get("Rx Packets")), _int(values.get("Tx Packets"))
            rx_multicast = _int(values.get("Rx Multicast"))
            counters[f"eth{n}"] = {
                "tx_errors": _int(values.get("Tx Errors")),
                "rx_errors": _int(values.get("Rx Errors")),
                "tx_discards": -1,
                "rx_discards": -1,
                "tx_octets": _int(values.get("Tx Bytes")),
                "rx_octets": _int(values.get("Rx Bytes")),
                "tx_unicast_packets": tx_packets,
                "rx_unicast_packets": (
                    rx_packets - rx_multicast if rx_packets >= 0 and rx_multicast >= 0 else rx_packets
                ),
                "tx_multicast_packets": -1,
                "rx_multicast_packets": rx_multicast,
                "tx_broadcast_packets": -1,
                "rx_broadcast_packets": -1,
            }
        return counters

    def get_snmp_information(self) -> models.SNMPDict:
        """Return the SNMP engine ID, contact, location and v1/v2c communities."""
        values = dict(_pairs(self._send_command("show snmp")))
        community: dict[str, models.SNMPCommunityDict] = {}
        v1_v2c = any(_value(values.get(key)).lower() == "enabled" for key in ("v1", "v2c"))
        if v1_v2c:
            for mode in ("ro", "rw"):
                name = _value(values.get(f"v1/v2c {mode.upper()} Community"))
                if name:
                    community[name] = {"acl": "N/A", "mode": mode}
        return {
            "chassis_id": _value(values.get("Engine Id")),
            "community": community,
            "contact": _value(values.get("Contact")),
            "location": _value(values.get("Location")),
        }

    def get_ntp_servers(self) -> dict[str, models.NTPServerDict]:
        """Return the configured local and public NTP servers."""
        servers: dict[str, models.NTPServerDict] = {}
        for key, value in _pairs(self._send_command("show ntp")):
            if re.fullmatch(r"Local Server #\d+|Public Server", key) and _value(value):
                servers[_value(value).split()[0]] = {}
        return servers

    def get_users(self) -> dict[str, models.UsersDict]:
        """Return local users. Administrators are level 15, Power Users 10, others 1."""
        output = self._send_command("show localusers")
        users: dict[str, models.UsersDict] = {}
        in_table = False
        for line in output.splitlines():
            if line.startswith("===="):
                in_table = True
                continue
            if not in_table or not line.strip():
                continue
            if re.match(r"\d+ user\(s\)\.", line):
                break
            fields = line.split()
            if len(fields) >= 3:
                users[fields[0]] = {
                    "level": _GROUP_LEVELS.get(fields[2].lower(), 1),
                    "password": "",
                    "sshkeys": [],
                }
        return users

    def _export_config(self) -> str:
        if self.device is None:
            raise ConnectionClosedException("Connection is not open")
        output = self.device.send_command_timing(
            "admin config commands copypaste", strip_prompt=False, strip_command=True
        )
        if "Do you want to continue?" in output:
            output = self.device.send_command(
                "yes", expect_string=PROMPT_PATTERN, read_timeout=max(self.timeout, 120)
            )
        output = output.replace("\r\n", "\n").replace("\r", "\n")
        lines = [line for line in output.split("\n") if not _EXPORT_NOISE.match(line)]
        return "\n".join(lines).strip("\n") + "\n"

    def get_config(
        self,
        retrieve: str = "all",
        full: bool = False,
        sanitized: bool = False,
        format: str = "text",
    ) -> models.ConfigDict:
        """Return the running configuration as CLI commands.

        The export is the device's own "admin config commands copypaste" output, which it
        can restore with "admin config batch". There is no startup or candidate
        configuration, so those are always empty.
        """
        if format != "text":
            raise NotImplementedError(f"{format} is not a supported format")
        config: models.ConfigDict = {"running": "", "startup": "", "candidate": ""}
        if retrieve in ("all", "running"):
            running = self._export_config()
            config["running"] = sanitize_config(running) if sanitized else running
        return config
