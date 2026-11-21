# De'Longhi Coffee Link for Home Assistant

Control and monitor De'Longhi coffee machines that use the **De'Longhi Coffee Link** app
(Ayla Networks cloud), with no add-on and no local server.

Developed and tested on an **Eletta Explore ECAM450.65.G** (firmware `Striker_cb`), which
only talks to the cloud: its local LAN mode is disabled. Other Coffee Link machines that use
the same protocol (Eletta Explore, PrimaDonna Soul, Dinamica Plus …) will probably work too.
Reports are welcome.

## Features

| Entity | What it does |
|---|---|
| `switch.coffee_machine_power` | Wake up (with the startup rinse) / standby |
| `button.coffee_machine_<drink>` | Brew a drink, one button per drink the integration has *learned* |
| `button.coffee_machine_stop_drink` | Stop the drink last started from Home Assistant |
| `sensor.coffee_machine_status` | standby, waking up, ready, rinsing, descaling … |
| `sensor.coffee_machine_progress` | Progress of the current operation (%) |
| `binary_sensor.coffee_machine_busy` | On while brewing, rinsing or heating up |
| Problem sensors | Water tank empty / removed, grounds container full / missing |
| Counters | Total beverages, espressos, coffees, long coffees, grounds count, descaling count |

### Verification status (Eletta Explore, Striker cb)

| Feature | Status |
|---|---|
| Login, status, progress, counters, power on / standby, espresso brew | ✅ verified on the machine |
| Water tank removed, grounds container missing | ✅ consistent with recorded monitor frames |
| Water tank empty, grounds container full | ⚠️ bit positions not yet verified |
| Stop drink | ⚠️ frame derivation verified against the app, not yet on the machine |

### How drinks are learned

Recipes differ per machine and per user profile, so the integration doesn't guess the
bytes. **Make a drink once in the official De'Longhi app** and the integration picks up
the exact command your app sent from the cloud history (checked every 10 minutes, or
press *Learn drinks from app*). A button for that drink then appears. Your app settings
(size, strength) are kept.

## Installation

### HACS (recommended)
1. HACS → ⋮ → *Custom repositories* → add `https://github.com/ondrejcech/ha-delonghi-coffeelink`, category *Integration*.
2. Install **De'Longhi Coffee Link** and restart Home Assistant.

### Manual
Copy `custom_components/delonghi_coffeelink` to `/config/custom_components/` and restart.

## Setup

*Settings → Devices & services → Add integration → De'Longhi Coffee Link*, then log in with
your Coffee Link app email and password. The machine on your account is found automatically.

The password is stored in the config entry so the integration can log in again by itself
if the cloud session is lost. If that fails, Home Assistant asks you to re-authenticate.

## How it works

* **Cloud only.** Commands and state go through the Ayla EU cloud the official app uses.
* **Live status.** The machine only pushes its status while an "app" is registered, so the
  integration registers its own app id (`CAFE4A55`) and renews it every 4 minutes. It
  never takes over while the phone app is connected; it then reads the status the phone
  app triggers.
* **Polling.** Every 60 s in standby, every 15 s when ready, every 3 s while busy.
* **Single-use tokens.** Ayla refresh tokens rotate on every use; each new token is
  saved to the config entry immediately.

## CLI

`cli/coffee.py` uses the same code from your terminal (needs `requests`):

```sh
mkdir -p .secrets && echo '{"email": "...", "password": "..."}' > .secrets/credentials.json
python cli/coffee.py login
python cli/coffee.py status        # read-only
python cli/coffee.py recipes       # learn drinks from the app history
python cli/coffee.py on --yes      # physical actions need --yes
python cli/coffee.py brew espresso --yes
python cli/coffee.py watch --yes --seconds 60
```

`.secrets/` is gitignored.

## Credits

Protocol knowledge builds on the work of
[cremalink](https://github.com/miditkl/cremalink) by Midian Tekle Elfu. This project is an
independent implementation and does not include cremalink code.

Not affiliated with De'Longhi. Use at your own risk.

## License

MIT
