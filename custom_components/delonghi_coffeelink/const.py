"""Constants for the De'Longhi Coffee Link integration."""
from datetime import timedelta

DOMAIN = "delonghi_coffeelink"

CONF_DSN = "dsn"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_ACCESS_TOKEN = "access_token"
CONF_EXPIRES_AT = "expires_at"

INTERVAL_STANDBY = timedelta(seconds=60)
INTERVAL_IDLE = timedelta(seconds=15)
INTERVAL_BUSY = timedelta(seconds=3)

COUNTERS_EVERY = 600  # seconds
ONLINE_EVERY = 300
LEARN_EVERY = 600

STORAGE_VERSION = 1
