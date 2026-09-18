"""Fluxul de configurare pentru Nova Energy România.

Pasul 1 cere credențialele și le validează printr-o autentificare reală.
Pasul 2 afișează conturile descoperite automat, ca să poată fi alese.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import NovaApiClient, NovaApiError, NovaAuthError
from .const import (
    CONF_ACCOUNTS,
    CONF_SELECT_ALL,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)
from .helpers import build_account_options, extract_accounts, resolve_selection

_LOGGER = logging.getLogger(__name__)

INTERVAL_MINIM = 300


def _schema_autentificare(implicite: dict | None = None) -> vol.Schema:
    implicite = implicite or {}
    return vol.Schema(
        {
            vol.Required(CONF_USERNAME, default=implicite.get(CONF_USERNAME, "")): cv.string,
            vol.Required(CONF_PASSWORD, default=implicite.get(CONF_PASSWORD, "")): cv.string,
            vol.Required(
                CONF_UPDATE_INTERVAL,
                default=implicite.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
            ): vol.All(cv.positive_int, vol.Clamp(min=INTERVAL_MINIM)),
        }
    )


def _schema_conturi(conturi: list[dict], selectate: list[str] | None = None) -> vol.Schema:
    optiuni = {
        optiune["value"]: optiune["label"] for optiune in build_account_options(conturi)
    }
    return vol.Schema(
        {
            vol.Optional(CONF_ACCOUNTS, default=selectate or []): cv.multi_select(optiuni),
            vol.Optional(CONF_SELECT_ALL, default=False): cv.boolean,
        }
    )


async def _descopera_conturi(hass, email: str, parola: str) -> list[dict]:
    """Se autentifică și întoarce conturile disponibile."""
    client = NovaApiClient(async_get_clientsession(hass), email, parola)
    payload = await client.async_login()
    return extract_accounts(payload)


class NovaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configurarea inițială a integrării."""

    VERSION = 1

    def __init__(self) -> None:
        self._date_autentificare: dict[str, Any] = {}
        self._conturi: list[dict] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pasul 1 — credențiale."""
        erori: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_USERNAME].strip()
            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()

            try:
                self._conturi = await _descopera_conturi(
                    self.hass, email, user_input[CONF_PASSWORD]
                )
            except NovaAuthError:
                erori["base"] = "invalid_auth"
            except NovaApiError:
                erori["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001 - orice altceva rămâne vizibil în log
                _LOGGER.exception("Eroare neașteptată la autentificare")
                erori["base"] = "unknown"
            else:
                if not self._conturi:
                    erori["base"] = "no_accounts"
                else:
                    self._date_autentificare = {**user_input, CONF_USERNAME: email}
                    return await self.async_step_accounts()

        return self.async_show_form(
            step_id="user", data_schema=_schema_autentificare(user_input), errors=erori
        )

    async def async_step_accounts(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pasul 2 — selecția conturilor."""
        erori: dict[str, str] = {}

        if user_input is not None:
            selectate = resolve_selection(
                user_input.get(CONF_ACCOUNTS, []),
                self._conturi,
                toate_bifate=user_input.get(CONF_SELECT_ALL, False),
            )
            if not selectate:
                erori["base"] = "no_selection"
            else:
                return self.async_create_entry(
                    title=self._date_autentificare[CONF_USERNAME],
                    data={**self._date_autentificare, CONF_ACCOUNTS: selectate},
                )

        return self.async_show_form(
            step_id="accounts",
            data_schema=_schema_conturi(self._conturi),
            errors=erori,
            description_placeholders={"numar": str(len(self._conturi))},
        )

    # ──────────────────────────────────────────
    # Reautentificare
    # ──────────────────────────────────────────
    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Pornit de Home Assistant când credențialele nu mai sunt acceptate."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Cere doar parola nouă: emailul identifică intrarea și nu se schimbă."""
        intrare = self._get_reauth_entry()
        erori: dict[str, str] = {}

        if user_input is not None:
            try:
                conturi = await _descopera_conturi(
                    self.hass, intrare.data[CONF_USERNAME], user_input[CONF_PASSWORD]
                )
            except NovaAuthError:
                erori["base"] = "invalid_auth"
            except NovaApiError:
                erori["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Eroare neașteptată la reautentificare")
                erori["base"] = "unknown"
            else:
                if not conturi:
                    erori["base"] = "no_accounts"
                else:
                    return self.async_update_reload_and_abort(
                        intrare,
                        data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]},
                    )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): cv.string}),
            errors=erori,
            description_placeholders={"email": intrare.data[CONF_USERNAME]},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> NovaOptionsFlow:
        """Întoarce fluxul de reconfigurare."""
        return NovaOptionsFlow()


class NovaOptionsFlow(OptionsFlow):
    """Reconfigurare fără reinstalare."""

    def __init__(self) -> None:
        self._conturi: list[dict] = []

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Formular unic: interval + selecția conturilor."""
        intrare = self.config_entry
        erori: dict[str, str] = {}

        email = intrare.data[CONF_USERNAME]
        parola = intrare.data[CONF_PASSWORD]

        if not self._conturi:
            try:
                self._conturi = await _descopera_conturi(self.hass, email, parola)
            except NovaAuthError:
                erori["base"] = "invalid_auth"
            except NovaApiError:
                erori["base"] = "cannot_connect"

        if user_input is not None and not erori:
            selectate = resolve_selection(
                user_input.get(CONF_ACCOUNTS, []),
                self._conturi,
                toate_bifate=user_input.get(CONF_SELECT_ALL, False),
            )
            if not selectate:
                erori["base"] = "no_selection"
            else:
                return self.async_create_entry(
                    data={
                        CONF_UPDATE_INTERVAL: user_input[CONF_UPDATE_INTERVAL],
                        CONF_ACCOUNTS: selectate,
                    }
                )

        selectate_curent = list(
            intrare.options.get(CONF_ACCOUNTS, intrare.data.get(CONF_ACCOUNTS, []))
        )
        interval_curent = intrare.options.get(
            CONF_UPDATE_INTERVAL,
            intrare.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        )

        schema = _schema_conturi(self._conturi, selectate_curent).extend(
            {
                vol.Required(CONF_UPDATE_INTERVAL, default=interval_curent): vol.All(
                    cv.positive_int, vol.Clamp(min=INTERVAL_MINIM)
                )
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema, errors=erori)
