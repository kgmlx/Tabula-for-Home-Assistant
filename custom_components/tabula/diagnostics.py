from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_API_KEY
from .coordinator import TabulaCoordinator

TO_REDACT = {CONF_API_KEY, "api_key_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coord: TabulaCoordinator = entry.runtime_data
    snap = coord.data
    company = snap.inspect.company
    key = snap.inspect.api_key

    out: dict[str, Any] = {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "company": {"id": company.id, "name": company.name},
        "api_key": {
            "name": key.name,
            "created_at": key.created_at,
            "expires_at": key.expires_at,
        },
        "rate_limit": {
            "limit": snap.rate_limit_limit,
            "remaining": snap.rate_limit_remaining,
        },
    }
    out["last_upload"] = snap.last_upload
    out["last_batch"] = snap.last_batch
    out["last_request_id"] = coord.client.last_request_id
    return out
