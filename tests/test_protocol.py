"""Protocol tests using frames captured from a real Eletta Explore (Striker cb)."""
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "custom_components" / "delonghi_coffeelink"))

from api import protocol as p  # noqa: E402

# Official-app hot water start/stop pair
HW_START = bytes.fromhex("0d1183f010030f00961b011c012701065baa")
HW_STOP = bytes.fromhex("0d0f83f010020f00961b011c01066863")
ESPRESSO = bytes.fromhex("0d1183f00103010055020408002701063101")


def test_crc_on_known_frames():
    for f in (HW_START, HW_STOP, ESPRESSO, bytes.fromhex(p.FRAME_WAKEUP),
              bytes.fromhex(p.FRAME_STANDBY), bytes.fromhex(p.FRAME_REFRESH)):
        assert p.crc_ok(f), f.hex()


def test_derive_stop_matches_official_app():
    assert p.derive_stop(HW_START) == HW_STOP


def test_encode_request_layout():
    b64 = p.encode_request(p.FRAME_WAKEUP, "00F10C9F", now=0x6AFDC595)
    # byte-for-byte what the official app sent on 2026-11-18
    assert base64.b64decode(b64).hex() == "0d07840f020155126afdc59500f10c9f"


def test_registration_layout():
    assert base64.b64decode(p.encode_registration("00F10C9F", now=0x6B01C077)).hex() == "6b01c07700f10c9f"


def test_app_id_roundtrip():
    assert p.app_id_to_cloud("C0FFEEEE") == "-1056968978"
    assert p.app_id_from_cloud("-1056968978") == "C0FFEEEE"
    assert p.app_id_from_cloud("15797407") == "00F10C9F"
    assert p.app_id_from_cloud("0") is None


def test_parse_monitor_ready_and_brewing():
    ready = p.parse_monitor("0BJ1DwCAAAAABwAAAAAAAAB8AmsBwHo=")
    assert ready.status_name == "ready" and ready.action == 0 and not ready.is_busy
    assert ready.is_on and not ready.water_tank_empty and not ready.waste_container_full


def test_recipe_from_request():
    b64 = base64.b64encode(ESPRESSO + bytes.fromhex("6b01c6d4") + bytes.fromhex("00f10c9f")).decode()
    r = p.recipe_from_request(b64, "2026-11-21T16:34:42Z")
    assert r.beverage_id == 1 and r.name == "Espresso" and r.start == ESPRESSO.hex()
    assert r.stop == "0d0f83f001020100550204080006c180"
    wake = base64.b64encode(bytes.fromhex(p.FRAME_WAKEUP) + bytes(8)).decode()
    assert p.recipe_from_request(wake) is None


def test_serial():
    assert p.decode_serial("0BuhDwDNVEVTVDAwWlowMDAwMDBYMDAwMADvLg==") == "TEST00ZZ000000X0000"
