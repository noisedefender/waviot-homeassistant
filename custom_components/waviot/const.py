"""Constants for the WAVIoT integration."""

DOMAIN = "waviot"

# Where the cabinet lives and where authentication happens.
AUTH_URL = "https://auth.waviot.ru/?action=user-login&true_api=1"
API_BASE = "https://lk.waviot.ru"
API_DOCS_URL = "https://lk.waviot.ru/api/"

USER_AGENT = "HomeAssistant WAVIoT integration"

DEFAULT_POLL_INTERVAL_MINUTES = 15

CONF_LOGIN = "login"
CONF_PASSWORD = "password"
CONF_API_KEY = "api_key"
CONF_ELEMENT_ID = "element_id"
CONF_POLL_INTERVAL = "poll_interval_minutes"

# Units the cabinet reports for cumulative meter channels, mapped to Home
# Assistant units. Anything else is an instantaneous value and is not exposed.
UNIT_MAP = {
    "kWh": "kWh",
    "кВт·ч": "kWh",
    "кВтч": "kWh",
    "кВт*ч": "kWh",
    "кВт.ч": "kWh",
    "м³": "m³",
    "м3": "m³",
}
