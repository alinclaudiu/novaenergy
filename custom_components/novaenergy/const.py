"""Constante pentru integrarea Nova Energy România."""

from homeassistant.const import Platform

DOMAIN = "novaenergy"

# ──────────────────────────────────────────────
# Configurare implicită
# ──────────────────────────────────────────────
DEFAULT_UPDATE_INTERVAL = 21600  # 6 ore, în secunde
API_TIMEOUT = 30

# ──────────────────────────────────────────────
# Chei în config entry
# ──────────────────────────────────────────────
CONF_ACCOUNTS = "selected_accounts"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_SELECT_ALL = "select_all"

# ──────────────────────────────────────────────
# URL-uri API
# ──────────────────────────────────────────────
API_BASE = "https://backend.nova-energy.ro/api"

URL_LOGIN = f"{API_BASE}/accounts/login/client"
URL_SWITCH = f"{API_BASE}/accounts/switch"
URL_ME = f"{API_BASE}/accounts/me"
URL_APP_INFO = f"{API_BASE}/globals/app-info/general"
URL_METERING_POINTS = f"{API_BASE}/metering-points"
URL_CONSUMPTION_AGREEMENTS = f"{API_BASE}/metering-points/{{point_id}}/consumption-agreements"
URL_SELF_READINGS = f"{API_BASE}/self-readings"
URL_INVOICES = f"{API_BASE}/invoices"
URL_BALANCES = f"{API_BASE}/balances"
URL_CONTRACTS = f"{API_BASE}/contracts"
URL_PAYMENTS = f"{API_BASE}/payments"

HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
}

# ──────────────────────────────────────────────
# Utilități
# ──────────────────────────────────────────────
UTILITY_GAS = "gas"
UTILITY_ELECTRICITY = "electricity"

UTILITY_LABELS_RO = {
    UTILITY_GAS: "Gaz",
    UTILITY_ELECTRICITY: "Energie Electrică",
}

UTILITY_SLUG_RO = {
    UTILITY_GAS: "gaz",
    UTILITY_ELECTRICITY: "electricitate",
}

# Valoarea afișată când o dată lipsește sau nu poate fi interpretată.
VALOARE_NECUNOSCUTA = "—"

PLATFORMS: list[Platform] = [Platform.SENSOR]

ATTRIBUTION = "Date furnizate de Nova Power & Gas"
PRODUCATOR = "Nova Power & Gas"
