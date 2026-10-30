"""Raport de diagnostic pentru integrarea Nova Energy România.

Se atașează la tichetele de suport. Nu conține parole, tokenuri sau adresa de
email în clar.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONF_ACCOUNTS, CONF_UPDATE_INTERVAL, DOMAIN
from .helpers import mask_email


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Construiește raportul de diagnostic."""
    date_rulare = getattr(entry, "runtime_data", None)

    conturi: dict[str, Any] = {}
    if date_rulare is not None:
        for crm, coordinator in getattr(date_rulare, "coordinators", {}).items():
            date = coordinator.data or {}
            conturi[crm] = {
                "ultima_actualizare_reusita": coordinator.last_update_success,
                "utilitati": date.get("utilities", []),
                "numar_facturi": len(date.get("invoices", [])),
                "numar_plati": len(date.get("payments", [])),
                "numar_contracte": len(date.get("contracts", [])),
                "numar_puncte_masurare": len(date.get("metering_points", [])),
                "numar_citiri_index": len(date.get("self_readings", [])),
                "numar_contoare": len(date.get("meters", [])),
                # Ce nu s-a putut aduce explică de ce lipsesc unii senzori.
                "endpointuri_esuate": sorted(date.get("endpointuri_esuate", [])),
            }

    # Doar senzorii acestei intrări: cu două conturi Nova configurate, raportul
    # unuia nu are voie să conțină identificatorii celuilalt.
    senzori = sorted(
        intrare.entity_id
        for intrare in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if intrare.domain == "sensor"
    )
    activi = [
        entitate
        for entitate in senzori
        if (stare := hass.states.get(entitate)) is not None
        and stare.state != STATE_UNAVAILABLE
    ]

    return {
        "intrare": {
            "titlu": mask_email(entry.title),
            "versiune": entry.version,
            "domeniu": DOMAIN,
            "utilizator": mask_email(entry.data.get(CONF_USERNAME, "")),
            "interval_actualizare": entry.options.get(
                CONF_UPDATE_INTERVAL, entry.data.get(CONF_UPDATE_INTERVAL)
            ),
            "conturi_selectate": entry.options.get(
                CONF_ACCOUNTS, entry.data.get(CONF_ACCOUNTS, [])
            ),
        },
        "conturi": conturi,
        "stare": {
            "senzori_activi": len(activi),
            "lista_senzori": senzori,
        },
    }
