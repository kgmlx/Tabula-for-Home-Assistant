from __future__ import annotations

import asyncio
from functools import partial
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .api import (
    TabulaAuthError,
    TabulaConflictError,
    TabulaError,
    TabulaNotFoundError,
    TabulaRateLimitError,
)
from .const import (
    ATTR_BATCH_ID,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_DOCUMENT_TYPE,
    ATTR_EXTERNAL_ID,
    ATTR_PATH,
    ATTR_POLL,
    ATTR_UPLOAD_ID,
    BATCH_TERMINAL,
    DOCUMENT_TYPES,
    DOMAIN,
    EVENT_BATCH,
    EVENT_UPLOAD,
    UPLOAD_TERMINAL,
)
from .coordinator import TabulaCoordinator

SERVICE_UPLOAD_DOCUMENT = "upload_document"
SERVICE_UPLOAD_BATCH = "upload_batch"
SERVICE_GET_UPLOAD = "get_upload"
SERVICE_GET_BATCH = "get_batch"

DEFAULT_POLL_SECONDS = 5.0
MAX_POLL_SECONDS = 60.0

ENTRY_FIELD = {vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string}

UPLOAD_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PATH): cv.string,
        vol.Optional(ATTR_DOCUMENT_TYPE, default="auto"): vol.In(DOCUMENT_TYPES),
        vol.Optional(ATTR_EXTERNAL_ID): cv.string,
        vol.Optional(ATTR_POLL, default=True): cv.boolean,
        **ENTRY_FIELD,
    }
)

BATCH_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PATH): cv.string,
        vol.Optional(ATTR_DOCUMENT_TYPE, default="auto"): vol.In(DOCUMENT_TYPES),
        vol.Optional(ATTR_EXTERNAL_ID): cv.string,
        vol.Optional(ATTR_POLL, default=True): cv.boolean,
        **ENTRY_FIELD,
    }
)

GET_UPLOAD_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_UPLOAD_ID): cv.string,
        vol.Optional(ATTR_POLL, default=False): cv.boolean,
        **ENTRY_FIELD,
    }
)

GET_BATCH_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_BATCH_ID): cv.string,
        vol.Optional(ATTR_POLL, default=False): cv.boolean,
        **ENTRY_FIELD,
    }
)


def _resolve_path(hass: HomeAssistant, path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = Path(hass.config.path(path_str))
    path = path.resolve()

    allowed = [
      Path(hass.config.config_dir).resolve(),
        Path(hass.config.path("www")).resolve(),
    ]
    for media_path in (getattr(hass.config, "media_dirs", None) or {}).values():
        allowed.append(Path(media_path).resolve())

    if not any(path == root or root in path.parents for root in allowed):
        raise ServiceValidationError(
            f"Path must be under config or media: {path}"
        )
    if not path.is_file():
        raise ServiceValidationError(f"File not found: {path}")
    return path


def _guess_content_type(path: Path) -> str:
    # TODO: sniff magic bytes instead of trusting the extension
    ext = path.suffix.lower()
    if ext == ".pdf":
        return "application/pdf"
    elif ext == ".xml":
        return "application/xml"
    elif ext == ".zip":
        return "application/zip"
    else:
        return "application/octet-stream"


def _loaded_entries(
    hass: HomeAssistant, *, exclude_entry_id: str | None = None
) -> dict[str, TabulaCoordinator]:
    return {
        entry.entry_id: entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
        and entry.entry_id != exclude_entry_id
    }


def _coordinator(hass: HomeAssistant, call: ServiceCall) -> TabulaCoordinator:
    loaded = _loaded_entries(hass)
    if not loaded:
        raise HomeAssistantError("Tabula is not set up")

    entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if entry_id:
        if entry_id not in loaded:
            raise ServiceValidationError(f"Unknown Tabula config entry: {entry_id}")
        return loaded[entry_id]
    if len(loaded) > 1:
        raise ServiceValidationError(
            "Multiple Tabula companies are configured; pass config_entry_id"
        )
    return next(iter(loaded.values()))


def _map_error(err: TabulaError) -> HomeAssistantError:
    if isinstance(err, TabulaAuthError):
        return HomeAssistantError(f"Tabula authentication failed: {err}")
    if isinstance(err, TabulaRateLimitError):
        hint = f" Retry after {err.retry_after}s." if err.retry_after else ""
        return HomeAssistantError(f"Tabula rate limit reached.{hint}")
    if isinstance(err, TabulaNotFoundError):
        return HomeAssistantError(f"Tabula resource not found: {err}")
    if isinstance(err, TabulaConflictError):
        return HomeAssistantError(f"Tabula conflict: {err}")
    return HomeAssistantError(f"Tabula request failed: {err}")


async def _poll_upload(
    hass: HomeAssistant,
    coordinator: TabulaCoordinator,
    upload_id: str,
) -> dict[str, Any]:
    while True:
        try:
            upload, wait = await coordinator.client.get_upload(upload_id)
        except TabulaError as err:
            raise _map_error(err) from err

        coordinator.store_upload(upload)
        hass.bus.async_fire(EVENT_UPLOAD, {"upload": upload})
        if upload.get("status") in UPLOAD_TERMINAL:
            return upload
        await asyncio.sleep(min(wait or DEFAULT_POLL_SECONDS, MAX_POLL_SECONDS))


async def _poll_batch(
    hass: HomeAssistant,
    coordinator: TabulaCoordinator,
    batch_id: str,
) -> dict[str, Any]:
    client = coordinator.client
    while True:
        try:
            batch, wait = await client.get_upload_batch(batch_id)
        except TabulaError as err:
            raise _map_error(err) from err

        coordinator.store_batch(batch)
        hass.bus.async_fire(EVENT_BATCH, {"batch": batch})

        status = batch.get("status")
        if status in BATCH_TERMINAL:
            return batch

        delay = wait if wait is not None else DEFAULT_POLL_SECONDS
        await asyncio.sleep(min(delay, MAX_POLL_SECONDS))


async def async_upload_document(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    coordinator = _coordinator(hass, call)
    path = _resolve_path(hass, call.data[ATTR_PATH])
    blob = await hass.async_add_executor_job(path.read_bytes)

    try:
        upload = await coordinator.client.create_upload(
            content=blob,
            filename=path.name,
            document_type=call.data[ATTR_DOCUMENT_TYPE],
            external_id=call.data.get(ATTR_EXTERNAL_ID),
            content_type=_guess_content_type(path),
        )
    except TabulaError as err:
        raise _map_error(err) from err

    coordinator.store_upload(upload)
    hass.bus.async_fire(EVENT_UPLOAD, {"upload": upload})

    if call.data[ATTR_POLL] and upload.get("status") not in UPLOAD_TERMINAL:
        upload = await _poll_upload(hass, coordinator, upload["id"])

    return {"upload": upload}


async def async_upload_batch(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    coordinator = _coordinator(hass, call)
    path = _resolve_path(hass, call.data[ATTR_PATH])
    if path.suffix.lower() != ".zip":
        raise ServiceValidationError("Batch upload expects a .zip archive")

    blob = await hass.async_add_executor_job(path.read_bytes)

    try:
      batch = await coordinator.client.create_upload_batch(
            content=blob,
            filename=path.name,
            document_type=call.data[ATTR_DOCUMENT_TYPE],
            external_id=call.data.get(ATTR_EXTERNAL_ID),
        )
    except TabulaError as err:
        raise _map_error(err) from err

    coordinator.store_batch(batch)
    hass.bus.async_fire(EVENT_BATCH, {"batch": batch})

    if call.data[ATTR_POLL] and batch.get("status") not in BATCH_TERMINAL:
        batch = await _poll_batch(hass, coordinator, batch["id"])

    return {"batch": batch}


async def async_get_upload(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    coordinator = _coordinator(hass, call)
    upload_id = call.data[ATTR_UPLOAD_ID]

    if call.data[ATTR_POLL]:
        upload = await _poll_upload(hass, coordinator, upload_id)
    else:
        try:
            upload, _ = await coordinator.client.get_upload(upload_id)
        except TabulaError as err:
            raise _map_error(err) from err
        coordinator.store_upload(upload)
        hass.bus.async_fire(EVENT_UPLOAD, {"upload": upload})

    return {"upload": upload}


async def async_get_batch(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    coordinator = _coordinator(hass, call)
    batch_id = call.data[ATTR_BATCH_ID]

    if call.data[ATTR_POLL]:
        batch = await _poll_batch(hass, coordinator, batch_id)
    else:
        try:
            batch, _ = await coordinator.client.get_upload_batch(batch_id)
        except TabulaError as err:
            raise _map_error(err) from err
        coordinator.store_batch(batch)
        hass.bus.async_fire(EVENT_BATCH, {"batch": batch})

    return {"batch": batch}


async def async_setup_services(hass: HomeAssistant) -> None:
    if hass.data.setdefault(DOMAIN, {}).get("_services"):
        return

    hass.services.async_register(
        DOMAIN,
        SERVICE_UPLOAD_DOCUMENT,
        partial(async_upload_document, hass),
        schema=UPLOAD_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UPLOAD_BATCH,
        partial(async_upload_batch, hass),
        schema=BATCH_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_UPLOAD,
        partial(async_get_upload, hass),
        schema=GET_UPLOAD_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_BATCH,
        partial(async_get_batch, hass),
        schema=GET_BATCH_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.data[DOMAIN]["_services"] = True


async def async_unload_services(
    hass: HomeAssistant, *, unloading_entry_id: str | None = None
) -> None:
    if not hass.data.get(DOMAIN, {}).get("_services"):
        return
    if _loaded_entries(hass, exclude_entry_id=unloading_entry_id):
        return

    hass.services.async_remove(DOMAIN, SERVICE_UPLOAD_DOCUMENT)
    hass.services.async_remove(DOMAIN, SERVICE_UPLOAD_BATCH)
    hass.services.async_remove(DOMAIN, SERVICE_GET_UPLOAD)
    hass.services.async_remove(DOMAIN, SERVICE_GET_BATCH)
    hass.data[DOMAIN].pop("_services", None)
