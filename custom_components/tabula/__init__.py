from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TabulaClient
from .const import CONF_API_KEY, DEFAULT_BASE_URL, DOMAIN
from .coordinator import TabulaCoordinator
from .services import async_setup_services, async_unload_services

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry[TabulaCoordinator]
) -> bool:
    client = TabulaClient(
        async_get_clientsession(hass),
        entry.data[CONF_API_KEY],
        DEFAULT_BASE_URL,
    )
    coordinator = TabulaCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    hass.data.setdefault(DOMAIN, {})
    await async_setup_services(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ConfigEntry[TabulaCoordinator]
) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
      # FIXME: this still races if two entries unload at once
        await async_unload_services(hass, unloading_entry_id=entry.entry_id)
    return ok
