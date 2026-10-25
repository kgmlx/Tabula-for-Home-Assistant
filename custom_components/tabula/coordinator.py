from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    InspectResult,
    TabulaAuthError,
    TabulaClient,
    TabulaError,
    TabulaRateLimitError,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(minutes=30)


@dataclass
class TabulaData:
    inspect: InspectResult
    rate_limit_limit: int | None
    rate_limit_remaining: int | None
    last_upload: dict[str, Any] | None
    last_batch: dict[str, Any] | None


class TabulaCoordinator(DataUpdateCoordinator[TabulaData]):
    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: TabulaClient,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self.config_entry = entry
        self.last_upload: dict[str, Any] | None = None
        self.last_batch: dict[str, Any] | None = None

    async def _async_update_data(self) -> TabulaData:
        try:
            account = await self.client.inspect()
        except TabulaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except TabulaRateLimitError as err:
            raise UpdateFailed(retry_after=err.retry_after) from err
        except TabulaError as err:
            raise UpdateFailed(str(err)) from err

        return TabulaData(
            inspect=account,
            rate_limit_limit=self.client.rate_limit.limit,
            rate_limit_remaining=self.client.rate_limit.remaining,
            last_upload=self.last_upload,
            last_batch=self.last_batch,
        )

    def _push(self) -> None:
        if self.data is None:
            return
        self.async_set_updated_data(
            TabulaData(
                inspect=self.data.inspect,
                rate_limit_limit=self.client.rate_limit.limit,
                rate_limit_remaining=self.client.rate_limit.remaining,
                last_upload=self.last_upload,
                last_batch=self.last_batch,
            )
        )

    def store_upload(self, upload: dict[str, Any]) -> None:
        self.last_upload = upload
        self._push()

    def store_batch(self, batch: dict[str, Any]) -> None:
        self.last_batch = batch
        self._push()
