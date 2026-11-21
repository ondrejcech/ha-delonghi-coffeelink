#!/usr/bin/env python3
"""Command-line control for De'Longhi Coffee Link machines.

Uses the same `api` package as the Home Assistant integration.
Secrets live in <repo>/.secrets/ (gitignored):
  credentials.json  {"email": "...", "password": "..."}
  token.json        rotated Ayla tokens (written automatically)

Read-only:  login | info | status | counters | recipes
Writes:     on | off | brew <id|name> | stop <id|name> | watch   (need --yes)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "custom_components" / "delonghi_coffeelink"))

from api import protocol as p  # noqa: E402
from api.auth import LoginError, login  # noqa: E402
from api.cloud import AuthError, AylaClient, CloudError, Machine, Tokens  # noqa: E402

SECRETS = ROOT / ".secrets"
TOKEN_FILE = SECRETS / "token.json"
CREDS_FILE = SECRETS / "credentials.json"
RECIPES_FILE = SECRETS / "recipes.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # never world-readable
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    tmp.replace(path)


def make_client() -> AylaClient:
    t = _load(TOKEN_FILE)
    creds = _load(CREDS_FILE)
    return AylaClient(
        Tokens(t.get("refresh_token"), t.get("access_token"), t.get("expires_at", 0)),
        on_tokens=lambda tok: _save(TOKEN_FILE, tok.as_dict()),
        email=creds.get("email"),
        password=creds.get("password"),
    )


def make_machine(args) -> Machine:
    client = make_client()
    dsn = args.dsn or (client.devices() or [{}])[0].get("dsn")
    if not dsn:
        sys.exit("No machine on this account")
    return Machine(client, dsn)


def _age(s: str | None) -> str:
    if not s:
        return "never"
    ts = datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    sec = int(time.time() - ts)
    return f"{sec}s ago" if sec < 120 else f"{sec // 60}m ago" if sec < 7200 else f"{sec // 3600}h ago"


def _print_state(st) -> None:
    m = st.monitor
    if not m:
        print("monitor: no data")
        return
    alerts = [n for n in ("water_tank_empty", "water_tank_open", "waste_container_full", "waste_container_missing")
              if getattr(m, n)]
    print(f"status   : {m.status_name} ({m.status})   [monitor {_age(st.monitor_updated_at)}, app {st.registered_app}]")
    print(f"action   : {m.action}  progress {m.progress}%  busy={m.is_busy}")
    print(f"alerts   : {', '.join(alerts) or 'none'}   switches={m.switches.hex()} alarms={m.alarms.hex()}")


def recipes() -> dict[int, p.Recipe]:
    return {int(k): p.Recipe(**v) for k, v in _load(RECIPES_FILE).items()}


def find_recipe(arg: str) -> p.Recipe:
    rs = recipes()
    if arg.isdigit() and int(arg) in rs:
        return rs[int(arg)]
    for r in rs.values():
        if r.name.lower().replace(" ", "_") == arg.lower().replace(" ", "_"):
            return r
    sys.exit(f"Unknown recipe '{arg}'. Known: {', '.join(f'{r.beverage_id}={r.name}' for r in rs.values())}. "
             "Brew it once from the De'Longhi app, then run `recipes`.")


def need_yes(args, what: str) -> None:
    if not args.yes:
        sys.exit(f"Refusing to {what} without --yes (acts on the physical machine).")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dsn")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("login", "info", "status", "counters", "recipes"):
        sub.add_parser(name)
    for name in ("on", "off"):
        sub.add_parser(name).add_argument("--yes", action="store_true")
    for name in ("brew", "stop"):
        sp = sub.add_parser(name)
        sp.add_argument("recipe")
        sp.add_argument("--yes", action="store_true")
    sp = sub.add_parser("watch")
    sp.add_argument("--seconds", type=int, default=60)
    sp.add_argument("--interval", type=float, default=3)
    sp.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    try:
        if args.cmd == "login":
            c = _load(CREDS_FILE)
            refresh = login(c.get("email", ""), c.get("password", ""))
            _save(TOKEN_FILE, {"refresh_token": refresh})
            print("Login OK")
            return
        m = make_machine(args)
        if args.cmd == "info":
            print(f"dsn      : {m.dsn}")
            for k, v in m.info().items():
                print(f"{k:9}: {v}")
        elif args.cmd == "status":
            _print_state(m.poll())
        elif args.cmd == "counters":
            for k, v in m.poll(with_counters=True).counters.items():
                print(f"{k:28} {v}")
        elif args.cmd == "recipes":
            known = recipes()
            for bid, r in m.learn_recipes().items():
                known[bid] = r
            _save(RECIPES_FILE, {str(k): vars(v) for k, v in known.items()})
            for r in sorted(known.values(), key=lambda r: r.beverage_id):
                print(f"{r.beverage_id:4}  {r.name:24} learned {r.learned_at}  start={r.start}")
        elif args.cmd == "on":
            need_yes(args, "wake the machine")
            m.wake(); print("sent wakeup")
        elif args.cmd == "off":
            need_yes(args, "put the machine in standby")
            m.standby(); print("sent standby")
        elif args.cmd in ("brew", "stop"):
            r = find_recipe(args.recipe)
            need_yes(args, f"{args.cmd} {r.name}")
            (m.brew if args.cmd == "brew" else m.stop)(r)
            print(f"sent {args.cmd} {r.name}")
        elif args.cmd == "watch":
            need_yes(args, "register as an app for live status")
            end, last = time.time() + args.seconds, None
            while time.time() < end:
                st = m.poll()
                m.keepalive(st.registered_app)
                key = st.monitor.raw if st.monitor else None
                if key != last:
                    print(f"--- {datetime.now():%H:%M:%S}", flush=True)
                    _print_state(st)
                    sys.stdout.flush()
                    last = key
                time.sleep(args.interval)
    except (AuthError, LoginError) as e:
        sys.exit(f"Auth problem: {e}\nCheck {CREDS_FILE} and run: coffee.py login")
    except (CloudError, OSError) as e:
        sys.exit(f"Cloud problem: {e}")


if __name__ == "__main__":
    main()
