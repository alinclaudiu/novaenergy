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
# Backend-ul aplicației de client „MyAccount". Cel vechi,
# `backend.nova-energy.ro/api`, răspunde 404 la toate rutele de când Nova a
# trecut aplicația pe această platformă.
API_BASE = "https://myaccount-admin.nova-energy.ro/api/v1"

URL_LOGIN = f"{API_BASE}/auth/login"
URL_SWITCH = f"{API_BASE}/auth/switch-account"
URL_BALANCE = f"{API_BASE}/dashboard/balance"
URL_CONTRACTS = f"{API_BASE}/contracts"
URL_METERING_POINTS = f"{API_BASE}/metering-points"
URL_INVOICES = f"{API_BASE}/invoices"
URL_PAYMENTS = f"{API_BASE}/payments"
URL_SELF_READINGS = f"{API_BASE}/self-readings"

HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
}

# Antetul prin care aplicația oficială îi spune serverului ce cont vizualizează.
ANTET_CONT_VIZUALIZAT = "X-Viewed-Account"

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
