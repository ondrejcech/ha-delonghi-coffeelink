"""De'Longhi ECAM-over-Ayla frame protocol.

Frames are hex byte strings: 0x0d (request) / 0xd0 (response), a length byte,
the opcode and payload, then a CRC16-CCITT (init 0x1D0F). Requests written to
the cloud property `app_data_request` are base64(frame + 4-byte unix time +
4-byte app id). Registering an app id = writing base64(time + app id) to
`app_device_connected`; while an app is registered the machine pushes its
monitor frame (`d302_monitor_machine`) every couple of seconds.
"""
from __future__ import annotations

import base64
import binascii
import time
from dataclasses import dataclass, field

# Machine control frames (identical to what the official app sends).
FRAME_WAKEUP = "0d07840f02015512"
FRAME_STANDBY = "0d07840f01010041"
FRAME_REFRESH = "0d07840f03025640"

BREW_OPCODE = b"\x83\xf0"
OP_START_LEGACY = 0x01
OP_STOP = 0x02
OP_START = 0x03

PROP_MONITOR = "d302_monitor_machine"
PROP_REQUEST = "app_data_request"
PROP_CONNECTED = "app_device_connected"
PROP_APP_ID = "app_id"
PROP_FIRMWARE = "software_version"
PROP_SERIAL = "d270_serialnumber"

STATUS_NAMES: dict[int, str] = {
    0: "standby",
    1: "waking_up",
    2: "going_to_sleep",
    4: "descaling",
    5: "preparing_steam",
    7: "ready",
    8: "rinsing",
    10: "preparing_milk",
    11: "dispensing_hot_water",
    12: "cleaning_milk",
    14: "rinsing_water_filter",
    16: "preparing_chocolate",
}

# Beverage ids as used in brew frames and in the machine's recipe/counter
# property names (d001_rec_espresso -> 1, tot_id120_cold_brew_coffee -> 120 ...).
BEVERAGE_NAMES: dict[int, str] = {
    1: "Espresso", 2: "Coffee", 3: "Long Coffee", 4: "2x Espresso", 5: "Doppio+",
    6: "Americano", 7: "Cappuccino", 8: "Latte Macchiato", 9: "Caffelatte",
    10: "Flat White", 11: "Espresso Macchiato", 12: "Hot Milk", 13: "Cappuccino Doppio+",
    15: "Cappuccino Reverse", 16: "Hot Water", 22: "Tea", 23: "Coffee Pot", 24: "Cortado",
    27: "Brew Over Ice",
    50: "Iced Americano", 51: "Iced Cappuccino", 52: "Iced Latte Macchiato",
    53: "Iced Cappuccino Mix", 54: "Iced Flat White", 55: "Iced Cold Milk",
    56: "Iced Caffelatte", 57: "Over Ice Espresso",
    80: "Mug Americano", 81: "Mug Cappuccino", 82: "Mug Latte Macchiato",
    83: "Mug Caffelatte", 84: "Mug Cappuccino Mix", 85: "Mug Flat White", 86: "Mug Hot Milk",
    100: "Mug Over Ice", 101: "Mug Iced Americano", 102: "Mug Iced Cappuccino",
    103: "Mug Iced Latte Macchiato", 104: "Mug Iced Caffelatte", 105: "Mug Iced Cappuccino Mix",
    106: "Mug Iced Flat White", 107: "Mug Iced Cold Milk",
    120: "Cold Brew Coffee", 121: "Cold Brew Espresso", 122: "Cold Brew Pot",
    123: "Cold Brew Latte", 124: "Cold Brew Cappuccino", 140: "Cold Brew Mug",
    141: "Cold Brew Latte Mug", 142: "Cold Brew Cappuccino Mug",
    200: "Espresso (Bean Select)",
}


def beverage_name(bev_id: int) -> str:
    if 230 <= bev_id <= 235:
        return f"Custom {bev_id - 229}"
    return BEVERAGE_NAMES.get(bev_id, f"Beverage {bev_id}")


def crc16(data: bytes) -> int:
    crc = 0x1D0F
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def with_crc(frame_wo_crc: bytes) -> bytes:
    return frame_wo_crc + crc16(frame_wo_crc).to_bytes(2, "big")


def crc_ok(frame: bytes) -> bool:
    return len(frame) > 3 and crc16(frame[:-2]) == int.from_bytes(frame[-2:], "big")


def encode_request(frame_hex: str, app_id_hex: str, now: float | None = None) -> str:
    ts = int(now if now is not None else time.time()).to_bytes(4, "big")
    return base64.b64encode(bytes.fromhex(frame_hex) + ts + bytes.fromhex(app_id_hex)).decode()


def encode_registration(app_id_hex: str, now: float | None = None) -> str:
    ts = int(now if now is not None else time.time()).to_bytes(4, "big")
    return base64.b64encode(ts + bytes.fromhex(app_id_hex)).decode()


def app_id_to_cloud(app_id_hex: str) -> str:
    """Cloud stores app_id as a signed 32-bit decimal string."""
    v = int(app_id_hex, 16)
    return str(v - 2**32 if v >= 2**31 else v)


def app_id_from_cloud(value: str | int | None) -> str | None:
    if value in (None, "", "0", 0):
        return None
    return f"{int(value) & 0xFFFFFFFF:08X}"


def split_request(b64: str) -> tuple[bytes, str] | None:
    """Split a request datapoint into (frame, app id hex)."""
    try:
        raw = base64.b64decode(b64 or "")
    except (binascii.Error, ValueError):
        return None
    if len(raw) < 12 or raw[0] != 0x0D:
        return None
    frame = raw[: raw[1] + 1]
    if len(frame) < 8 or len(frame) != raw[1] + 1:
        return None
    return frame, raw[-4:].hex().upper()


def derive_stop(start_frame: bytes) -> bytes:
    """Stop frame for a brew start frame: op 0x02 and without param 0x27.

    Verified against the official app's hot-water start/stop pair.
    """
    body = bytes(start_frame[6:-2])  # params ... 0x06 (end marker)
    # The app puts "27 xx" last, right before the 0x06 end marker. Only strip it
    # there: a value byte elsewhere may legitimately be 0x27 (e.g. 39 ml).
    if len(body) >= 3 and body[-3] == 0x27:
        body = body[:-3] + body[-1:]
    frame = bytearray([0x0D, 0, 0x83, 0xF0, start_frame[4], OP_STOP]) + body
    frame[1] = len(frame) + 1
    return with_crc(bytes(frame))


@dataclass
class Recipe:
    beverage_id: int
    start: str  # hex frame incl. crc
    stop: str | None = None
    learned_at: str | None = None

    @property
    def name(self) -> str:
        return beverage_name(self.beverage_id)


def recipe_from_request(b64: str, created_at: str | None = None) -> Recipe | None:
    parts = split_request(b64)
    if not parts:
        return None
    frame, _ = parts
    if frame[2:4] != BREW_OPCODE or frame[5] not in (OP_START, OP_START_LEGACY) or not crc_ok(frame):
        return None
    return Recipe(frame[4], frame.hex(), derive_stop(frame).hex(), created_at)


@dataclass
class MonitorState:
    status: int
    action: int
    progress: int
    accessory: int
    switches: bytes
    alarms: bytes
    raw: bytes = field(repr=False)

    @property
    def status_name(self) -> str:
        return STATUS_NAMES.get(self.status, f"unknown_{self.status}")

    def _bit(self, data: bytes, byte: int, bit: int) -> bool:
        return len(data) > byte and bool(data[byte] >> bit & 1)

    @property
    def is_on(self) -> bool:
        return self.status not in (0, 2)

    @property
    def is_busy(self) -> bool:
        # In standby the machine keeps the last shutdown action (e.g. 2 @ 100%).
        return self.status != 0 and self.action != 0

    @property
    def water_tank_empty(self) -> bool:
        return self._bit(self.alarms, 0, 0)

    @property
    def waste_container_full(self) -> bool:
        return self._bit(self.alarms, 0, 1)

    @property
    def water_tank_open(self) -> bool:
        return self._bit(self.alarms, 1, 5)

    @property
    def waste_container_missing(self) -> bool:
        return self._bit(self.switches, 0, 3)


def parse_monitor(b64: str | None) -> MonitorState | None:
    if not b64:
        return None
    try:
        raw = base64.b64decode(b64)
    except (binascii.Error, ValueError):
        return None
    if len(raw) < 4 or raw[0] != 0xD0:
        return None
    length = raw[1]
    frame = raw[: length + 1]
    if not crc_ok(frame):
        return None
    c = frame[4:-2]  # skip d0, len, request id, answer flag
    if len(c) < 8:
        return None
    return MonitorState(
        accessory=c[0],
        switches=bytes(c[1:3]),
        alarms=bytes(c[3:5]) + bytes(c[8:10]),
        status=c[5],
        action=c[6],
        progress=c[7],
        raw=raw,
    )


def decode_serial(b64: str | None) -> str | None:
    if not b64:
        return None
    try:
        raw = base64.b64decode(b64)
    except (binascii.Error, ValueError):
        return None
    return raw[6:-3].decode("ascii", errors="replace").strip("\x00") or None
