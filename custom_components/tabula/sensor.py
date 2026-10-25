from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TabulaCoordinator, TabulaData

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class TabulaSensorDescription(SensorEntityDescription):
    value_fn: Callable[[TabulaData], str | int | None]
    attrs_fn: Callable[[TabulaData], dict[str, Any]] | None = None


def _expiry_state(data: TabulaData) -> str:
    expires = data.inspect.api_key.expires_at
    if not expires:
        return "never"
    return expires


SENSORS: tuple[TabulaSensorDescription, ...] = (
    TabulaSensorDescription(
        key="company",
        translation_key="company",
        value_fn=lambda d: d.inspect.company.name,
        attrs_fn=lambda d: {"company_id": d.inspect.company.id},
    ),
    TabulaSensorDescription(
        key="api_key",
        translation_key="api_key",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.inspect.api_key.name,
        attrs_fn=lambda d: {
            "api_key_id": d.inspect.api_key.id,
            "created_at": d.inspect.api_key.created_at,
            "expires_at": d.inspect.api_key.expires_at,
        },
    ),
    TabulaSensorDescription(
        key="api_key_expires",
        translation_key="api_key_expires",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_expiry_state,
    ),
    TabulaSensorDescription(
        key="rate_limit_remaining",
        translation_key="rate_limit_remaining",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.rate_limit_remaining,
        attrs_fn=lambda d: {"limit": d.rate_limit_limit},
    ),
    TabulaSensorDescription(
        key="last_upload_status",
        translation_key="last_upload_status",
        value_fn=lambda d: (d.last_upload or {}).get("status"),
        attrs_fn=lambda d: _upload_attrs(d.last_upload),
    ),
    TabulaSensorDescription(
        key="last_batch_status",
        translation_key="last_batch_status",
        value_fn=lambda d: (d.last_batch or {}).get("status"),
        attrs_fn=lambda d: _batch_attrs(d.last_batch),
    ),
)


def _upload_attrs(upload: dict[str, Any] | None) -> dict[str, Any]:
    if not upload:
        return {}
    outcome = upload.get("result") or {}
    err = upload.get("error") or {}
    return {
        "upload_id": upload.get("id"),
        "batch_id": upload.get("batchId"),
        "external_id": upload.get("externalId"),
        "file_name": upload.get("fileName"),
        "document_type": upload.get("documentType"),
        "created_at": upload.get("createdAt"),
        "result_type": outcome.get("type"),
        "result_id": outcome.get("id"),
        "result_url": outcome.get("url"),
        "error_code": err.get("code"),
        "error_message": err.get("message"),
    }


def _batch_attrs(batch: dict[str, Any] | None) -> dict[str, Any]:
    if not batch:
        return {}
    counts = batch.get("counts") or {}
    return {
        "batch_id": batch.get("id"),
        "external_id": batch.get("externalId"),
        "document_type": batch.get("documentType"),
        "created_at": batch.get("createdAt"),
        "total": counts.get("total"),
        "queued": counts.get("queued"),
        "processing": counts.get("processing"),
        "completed": counts.get("completed"),
        "failed": counts.get("failed"),
        "deleted": counts.get("deleted"),
        "uploads": [
            {
                "id": u.get("id"),
                "file_name": u.get("fileName"),
                "status": u.get("status"),
            }
            for u in batch.get("uploads") or []
        ],
    }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: TabulaCoordinator = entry.runtime_data
    async_add_entities(
        TabulaSensor(coordinator, description) for description in SENSORS
    )


class TabulaSensor(CoordinatorEntity[TabulaCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TabulaCoordinator,
        description: TabulaSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        company_id = coordinator.data.inspect.company.id
        self._attr_unique_id = f"{company_id}_{description.key}"
        # service entry - not a physical device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, company_id)},
            name=coordinator.data.inspect.company.name or "Tabula",
            manufacturer="Tabula",
            model="API",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> str | int | None:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)
