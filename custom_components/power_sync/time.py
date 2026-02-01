# custom_components/power_sync/time.py
from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory

from .const import (
    DOMAIN,
    CONF_ABC_NIGHT_START,
    CONF_ABC_NIGHT_END,
    CONF_ABC_EVENING_PEAK_START,
    CONF_ABC_EVENING_PEAK_END,
    DEFAULT_ABC_NIGHT_START,
    DEFAULT_ABC_NIGHT_END,
    DEFAULT_ABC_EVENING_PEAK_START,
    DEFAULT_ABC_EVENING_PEAK_END,
)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PowerSync time entities."""
    entities = [
        PowerSyncABCTime(
            entry,
            CONF_ABC_NIGHT_START,
            "ABC Night Start",
            DEFAULT_ABC_NIGHT_START,
            "mdi:weather-night"
        ),
        PowerSyncABCTime(
            entry,
            CONF_ABC_NIGHT_END,
            "ABC Night End",
            DEFAULT_ABC_NIGHT_END,
            "mdi:weather-sunset-up"
        ),
        PowerSyncABCTime(
            entry,
            CONF_ABC_EVENING_PEAK_START,
            "ABC Evening Peak Start",
            DEFAULT_ABC_EVENING_PEAK_START,
            "mdi:peak-performance"
        ),
        PowerSyncABCTime(
            entry,
            CONF_ABC_EVENING_PEAK_END,
            "ABC Evening Peak End",
            DEFAULT_ABC_EVENING_PEAK_END,
            "mdi:peak-performance"
        ),
    ]
    async_add_entities(entities)

class PowerSyncABCTime(TimeEntity):
    """Time entity for ABC configuration."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        entry: ConfigEntry,
        key: str,
        name: str,
        default_value: str,
        icon: str | None = None,
    ) -> None:
        self._entry = entry
        self._key = key
        self._attr_name = name
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        
        # Initial value parsing
        t_str = entry.options.get(key, default_value)
        try:
            h, m = map(int, t_str.split(":"))
            self._attr_native_value = time(hour=h, minute=m)
        except (ValueError, AttributeError):
            h, m = map(int, default_value.split(":"))
            self._attr_native_value = time(hour=h, minute=m)

    @property
    def native_value(self) -> time:
        """Return the current value."""
        t_str = self._entry.options.get(self._key)
        if t_str:
            try:
                h, m = map(int, t_str.split(":"))
                return time(hour=h, minute=m)
            except (ValueError, AttributeError):
                pass
        return self._attr_native_value

    async def async_set_value(self, value: time) -> None:
        """Update the setting."""
        new_options = dict(self._entry.options)
        new_options[self._key] = value.strftime("%H:%M")
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)
        self.async_write_ha_state()
