# custom_components/power_sync/number.py
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.const import PERCENTAGE, UnitOfPower

from .const import (
    DOMAIN,
    CONF_ABC_EMERGENCY_MIN_SOC_PERCENT,
    CONF_ABC_HIGH_PRICE_MIN_SOC_PERCENT,
    CONF_ABC_OVERNIGHT_LOAD_W,
    CONF_ABC_EXPORT_MIN_THRESHOLD_CENTS,
    CONF_ABC_DAY_SPIKE_EXPORT_THRESHOLD_CENTS,
    CONF_ABC_VERY_HIGH_EXPORT_THRESHOLD_CENTS,
    CONF_ABC_IMPORT_STABILISED_THRESHOLD_CENTS,
    CONF_ABC_BUFFER_MIN_MINUTES,
    CONF_ABC_MODE_CHANGE_MIN_SECONDS,
    DEFAULT_ABC_EMERGENCY_MIN_SOC_PERCENT,
    DEFAULT_ABC_HIGH_PRICE_MIN_SOC_PERCENT,
    DEFAULT_ABC_OVERNIGHT_LOAD_W,
    DEFAULT_ABC_EVENING_LOAD_W,
    DEFAULT_ABC_EXPORT_MIN_THRESHOLD_CENTS,
    DEFAULT_ABC_DAY_SPIKE_EXPORT_THRESHOLD_CENTS,
    DEFAULT_ABC_VERY_HIGH_EXPORT_THRESHOLD_CENTS,
    DEFAULT_ABC_IMPORT_STABILISED_THRESHOLD_CENTS,
    DEFAULT_ABC_TRANSIENT_DURATION_MIN,
    DEFAULT_ABC_BUFFER_MIN_MINUTES,
    DEFAULT_ABC_MODE_CHANGE_MIN_SECONDS,
    CONF_ABC_EVENING_LOAD_W,
    CONF_ABC_TRANSIENT_DURATION_MIN,
)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PowerSync number entities."""
    entities = [
        PowerSyncABCNumber(
            entry,
            CONF_ABC_EMERGENCY_MIN_SOC_PERCENT,
            "ABC Emergency Min SOC",
            DEFAULT_ABC_EMERGENCY_MIN_SOC_PERCENT,
            0, 100, 1, PERCENTAGE, "mdi:battery-alert",
            "power_sync_abc_emergency_min_soc"
        ),
        PowerSyncABCNumber(
            entry,
            CONF_ABC_HIGH_PRICE_MIN_SOC_PERCENT,
            "ABC High Price Min SOC",
            DEFAULT_ABC_HIGH_PRICE_MIN_SOC_PERCENT,
            0, 100, 1, PERCENTAGE, "mdi:battery-arrow-up",
            "power_sync_abc_high_price_min_soc"
        ),
        PowerSyncABCNumber(
            entry,
            CONF_ABC_OVERNIGHT_LOAD_W,
            "ABC Overnight Load",
            DEFAULT_ABC_OVERNIGHT_LOAD_W,
            0, 5000, 10, UnitOfPower.WATT, "mdi:home-lightning-bolt",
            "power_sync_abc_overnight_load"
        ),
        PowerSyncABCNumber(
            entry,
            CONF_ABC_EVENING_LOAD_W,
            "ABC Evening Load",
            DEFAULT_ABC_EVENING_LOAD_W,
            0, 5000, 10, UnitOfPower.WATT, "mdi:home-lightning-bolt",
            "power_sync_abc_evening_load"
        ),
        PowerSyncABCNumber(
            entry,
            CONF_ABC_TRANSIENT_DURATION_MIN,
            "ABC Transient Duration",
            DEFAULT_ABC_TRANSIENT_DURATION_MIN,
            0, 480, 5, "min", "mdi:timer-outline",
            "power_sync_abc_transient_duration"
        ),
        PowerSyncABCNumber(
            entry,
            CONF_ABC_DAY_SPIKE_EXPORT_THRESHOLD_CENTS,
            "ABC Day Spike Export Threshold",
            DEFAULT_ABC_DAY_SPIKE_EXPORT_THRESHOLD_CENTS,
            0, 1000, 0.5, "c/kWh", "mdi:trending-up",
            "power_sync_abc_day_spike_export_threshold"
        ),
        PowerSyncABCNumber(
            entry,
            CONF_ABC_EXPORT_MIN_THRESHOLD_CENTS,
            "ABC Export Minimum Earnings",
            DEFAULT_ABC_EXPORT_MIN_THRESHOLD_CENTS,
            -100, 100, 0.5, "c/kWh", "mdi:cash-minus",
            "power_sync_abc_export_min_threshold"
        ),
        PowerSyncABCNumber(
            entry,
            CONF_ABC_VERY_HIGH_EXPORT_THRESHOLD_CENTS,
            "ABC Very High Export Threshold",
            DEFAULT_ABC_VERY_HIGH_EXPORT_THRESHOLD_CENTS,
            0, 10000, 1, "c/kWh", "mdi:trending-up",
            "power_sync_abc_very_high_export_threshold"
        ),
        PowerSyncABCNumber(
            entry,
            CONF_ABC_IMPORT_STABILISED_THRESHOLD_CENTS,
            "ABC Import Stabilised Threshold",
            DEFAULT_ABC_IMPORT_STABILISED_THRESHOLD_CENTS,
            0, 1000, 0.5, "c/kWh", "mdi:trending-down",
            "power_sync_abc_import_stabilised_threshold"
        ),
        PowerSyncABCNumber(
            entry,
            CONF_ABC_BUFFER_MIN_MINUTES,
            "ABC Buffer Minimum Minutes",
            DEFAULT_ABC_BUFFER_MIN_MINUTES,
            0, 120, 1, "min", "mdi:timer-outline",
            "power_sync_abc_buffer_minimum_minutes"
        ),
        PowerSyncABCNumber(
            entry,
            CONF_ABC_MODE_CHANGE_MIN_SECONDS,
            "ABC Mode Change Min Seconds",
            DEFAULT_ABC_MODE_CHANGE_MIN_SECONDS,
            0, 600, 5, "s", "mdi:timer-sand",
            "power_sync_abc_mode_change_min_seconds"
        ),
    ]
    async_add_entities(entities)

class PowerSyncABCNumber(NumberEntity):
    """Number entity for ABC configuration."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        entry: ConfigEntry,
        key: str,
        name: str,
        default_value: float,
        min_value: float,
        max_value: float,
        step: float,
        unit: str | None = None,
        icon: str | None = None,
        suggested_object_id: str | None = None,
    ) -> None:
        self._entry = entry
        self._key = key
        self._attr_name = name
        self._attr_native_value = float(entry.options.get(key, default_value))
        self._attr_native_min_value = min_value
        self._attr_native_max_value = max_value
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_suggested_object_id = suggested_object_id

    @property
    def native_value(self) -> float:
        """Return the current value."""
        return float(self._entry.options.get(self._key, self._attr_native_value))

    async def async_set_native_value(self, value: float) -> None:
        """Update the setting."""
        new_options = dict(self._entry.options)
        new_options[self._key] = value
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)
        self.async_write_ha_state()
