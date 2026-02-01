"""Switch platform for PowerSync integration."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    DOMAIN,
    CONF_AUTO_SYNC_ENABLED,
    SWITCH_TYPE_AUTO_SYNC,
    SWITCH_TYPE_FORCE_DISCHARGE,
    SWITCH_TYPE_FORCE_CHARGE,
    SWITCH_TYPE_ADVANCED_BATTERY_CONTROL,
    DEFAULT_DISCHARGE_DURATION,
    ATTR_LAST_SYNC,
    ATTR_SYNC_STATUS,
    DATA_ABC_ACTIVE,
    DATA_ABC_CONTROLLER,
    CONF_ABC_USE_SOLCAST_GUARDRAIL,
    DEFAULT_ABC_USE_SOLCAST_GUARDRAIL,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up PowerSync switch entities."""
    # Detect Tesla by checking if tesla_energy_site_id is configured
    from .const import CONF_TESLA_ENERGY_SITE_ID
    tesla_site_id = entry.options.get(
        CONF_TESLA_ENERGY_SITE_ID,
        entry.data.get(CONF_TESLA_ENERGY_SITE_ID, "")
    )
    is_tesla = bool(tesla_site_id)
    _LOGGER.info(f"🔋 Switch setup: tesla_site_id='{tesla_site_id}', is_tesla={is_tesla}")

    entities = [
        AutoSyncSwitch(
            hass=hass,
            entry=entry,
            description=SwitchEntityDescription(
                key=SWITCH_TYPE_AUTO_SYNC,
                name="TOU control",
                icon="mdi:sync",
            ),
            suggested_object_id="power_sync_auto_sync"
        ),
    ]

    # Add Tesla-specific switches only if Tesla is selected as battery system
    if is_tesla:
        _LOGGER.info("Tesla battery system detected - adding force charge/discharge switches")
        entities.extend([
            ForceDischargeSwitch(
                hass=hass,
                entry=entry,
                description=SwitchEntityDescription(
                    key=SWITCH_TYPE_FORCE_DISCHARGE,
                    name="Force Discharge",
                    icon="mdi:battery-arrow-up",
                ),
                suggested_object_id="power_sync_force_discharge"
            ),
            ForceChargeSwitch(
                hass=hass,
                entry=entry,
                description=SwitchEntityDescription(
                    key=SWITCH_TYPE_FORCE_CHARGE,
                    name="Force Charge",
                    icon="mdi:battery-arrow-down",
                ),
                suggested_object_id="power_sync_force_charge"
            ),
            AdvancedBatteryControlSwitch(
                hass=hass,
                entry=entry,
                description=SwitchEntityDescription(
                    key=SWITCH_TYPE_ADVANCED_BATTERY_CONTROL,
                    name="Advanced battery control",
                    icon="mdi:battery-auto",
                ),
                suggested_object_id="power_sync_advanced_battery_control"
            ),
            AdvancedBatteryControlGuardrailSwitch(
                entry=entry,
                suggested_object_id="power_sync_abc_solcast_guardrail"
            ),
        ])

    async_add_entities(entities)


# custom_components/power_sync/switch.py
class AutoSyncSwitch(SwitchEntity):
    """Switch to enable/disable automatic TOU schedule syncing."""

    _attr_has_entity_name = True

    def __init__(
            self,
            hass: HomeAssistant,
            entry: ConfigEntry,
            description: SwitchEntityDescription,
            suggested_object_id: str | None = None,
    ) -> None:
        """Initialize the switch."""
        self.hass = hass
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_suggested_object_id = suggested_object_id

        # Initialize state from config
        self._attr_is_on = entry.options.get(
            CONF_AUTO_SYNC_ENABLED,
            entry.data.get(CONF_AUTO_SYNC_ENABLED, True),
        )

    @property
    def is_on(self) -> bool:
        """Return True if the switch is on."""
        return self._attr_is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        self._attr_is_on = True
        new_options = dict(self._entry.options)
        new_options[CONF_AUTO_SYNC_ENABLED] = True
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        self._attr_is_on = False
        new_options = dict(self._entry.options)
        new_options[CONF_AUTO_SYNC_ENABLED] = False
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        attrs: dict[str, Any] = {}

        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        amber_coordinator = entry_data.get("amber_coordinator")

        if amber_coordinator and getattr(amber_coordinator, "data", None):
            attrs[ATTR_LAST_SYNC] = amber_coordinator.data.get("last_update")

        attrs[ATTR_SYNC_STATUS] = "enabled" if self.is_on else "disabled"
        return attrs


class ForceDischargeSwitch(SwitchEntity):
    """Switch to manually force battery discharge mode."""

    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        description: SwitchEntityDescription,
        suggested_object_id: str | None = None,
    ) -> None:
        """Initialize the switch."""
        self.hass = hass
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_suggested_object_id = suggested_object_id
        self._attr_is_on = False
        self._discharge_expires_at: datetime | None = None
        self._duration_minutes: int = DEFAULT_DISCHARGE_DURATION
        self._cancel_expiry_timer = None

    @property
    def is_on(self) -> bool:
        """Return True if force discharge is active."""
        return self._attr_is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on force discharge mode."""
        # Log context to help debug if triggered by automation vs user
        context = kwargs.get("context")
        if context:
            _LOGGER.info("Force discharge switch activated (context: user_id=%s, parent_id=%s)",
                        context.user_id, context.parent_id)
        else:
            _LOGGER.info("Force discharge switch activated (no context - likely UI action)")
        _LOGGER.info("Activating force discharge mode for %d minutes", self._duration_minutes)

        # Get the duration from service call data if provided
        duration = kwargs.get("duration", self._duration_minutes)

        # Call the force discharge service
        try:
            await self.hass.services.async_call(
                DOMAIN,
                "force_discharge",
                {"duration": duration},
                blocking=True,
            )

            self._attr_is_on = True
            self._discharge_expires_at = datetime.now() + timedelta(minutes=duration)
            self._duration_minutes = duration

            # Set up expiry timer
            self._schedule_expiry_check()

            self.async_write_ha_state()

        except Exception as err:
            _LOGGER.error("Failed to activate force discharge: %s", err)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off force discharge mode (restore normal operation)."""
        _LOGGER.info("Deactivating force discharge mode, restoring normal operation")

        try:
            await self.hass.services.async_call(
                DOMAIN,
                "restore_normal",
                {},
                blocking=True,
            )

            self._attr_is_on = False
            self._discharge_expires_at = None

            # Cancel any pending expiry timer
            if self._cancel_expiry_timer:
                self._cancel_expiry_timer()
                self._cancel_expiry_timer = None

            self.async_write_ha_state()

        except Exception as err:
            _LOGGER.error("Failed to restore normal operation: %s", err)

    def _schedule_expiry_check(self) -> None:
        """Schedule periodic check for discharge expiry."""
        # Cancel any existing timer
        if self._cancel_expiry_timer:
            self._cancel_expiry_timer()

        @callback
        def _check_expiry(now: datetime) -> None:
            """Check if discharge has expired."""
            if self._discharge_expires_at and datetime.now() >= self._discharge_expires_at:
                _LOGGER.info("Force discharge expired, restoring normal operation")
                self._attr_is_on = False
                self._discharge_expires_at = None
                self._cancel_expiry_timer = None
                self.async_write_ha_state()
            elif self._attr_is_on:
                # Schedule next check
                self._schedule_expiry_check()

        # Check every 30 seconds
        self._cancel_expiry_timer = async_track_time_interval(
            self.hass, _check_expiry, timedelta(seconds=30)
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        attrs = {
            "duration_minutes": self._duration_minutes,
        }

        if self._discharge_expires_at:
            attrs["expires_at"] = self._discharge_expires_at.isoformat()
            remaining = self._discharge_expires_at - datetime.now()
            if remaining.total_seconds() > 0:
                attrs["remaining_minutes"] = int(remaining.total_seconds() / 60)
            else:
                attrs["remaining_minutes"] = 0

        return attrs

    async def async_will_remove_from_hass(self) -> None:
        """Clean up when entity is removed."""
        if self._cancel_expiry_timer:
            self._cancel_expiry_timer()
            self._cancel_expiry_timer = None


class ForceChargeSwitch(SwitchEntity):
    """Switch to manually force battery charge mode."""

    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        description: SwitchEntityDescription,
        suggested_object_id: str | None = None,
    ) -> None:
        """Initialize the switch."""
        self.hass = hass
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_suggested_object_id = suggested_object_id
        self._attr_is_on = False
        self._charge_expires_at: datetime | None = None
        self._duration_minutes: int = DEFAULT_DISCHARGE_DURATION  # Reuse same default
        self._cancel_expiry_timer = None

    @property
    def is_on(self) -> bool:
        """Return True if force charge is active."""
        return self._attr_is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on force charge mode."""
        _LOGGER.info("Activating force charge mode for %d minutes", self._duration_minutes)

        # Get the duration from service call data if provided
        duration = kwargs.get("duration", self._duration_minutes)

        # Call the force charge service
        try:
            await self.hass.services.async_call(
                DOMAIN,
                "force_charge",
                {"duration": duration},
                blocking=True,
            )

            self._attr_is_on = True
            self._charge_expires_at = datetime.now() + timedelta(minutes=duration)
            self._duration_minutes = duration

            # Set up expiry timer
            self._schedule_expiry_check()

            self.async_write_ha_state()

        except Exception as err:
            _LOGGER.error("Failed to activate force charge: %s", err)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off force charge mode (restore normal operation)."""
        _LOGGER.info("Deactivating force charge mode, restoring normal operation")

        try:
            await self.hass.services.async_call(
                DOMAIN,
                "restore_normal",
                {},
                blocking=True,
            )

            self._attr_is_on = False
            self._charge_expires_at = None

            # Cancel any pending expiry timer
            if self._cancel_expiry_timer:
                self._cancel_expiry_timer()
                self._cancel_expiry_timer = None

            self.async_write_ha_state()

        except Exception as err:
            _LOGGER.error("Failed to restore normal operation: %s", err)

    def _schedule_expiry_check(self) -> None:
        """Schedule periodic check for charge expiry."""
        # Cancel any existing timer
        if self._cancel_expiry_timer:
            self._cancel_expiry_timer()

        @callback
        def _check_expiry(now: datetime) -> None:
            """Check if charge has expired."""
            if self._charge_expires_at and datetime.now() >= self._charge_expires_at:
                _LOGGER.info("Force charge expired, restoring normal operation")
                self._attr_is_on = False
                self._charge_expires_at = None
                self._cancel_expiry_timer = None
                self.async_write_ha_state()
            elif self._attr_is_on:
                # Schedule next check
                self._schedule_expiry_check()

        # Check every 30 seconds
        self._cancel_expiry_timer = async_track_time_interval(
            self.hass, _check_expiry, timedelta(seconds=30)
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        attrs = {
            "duration_minutes": self._duration_minutes,
        }

        if self._charge_expires_at:
            attrs["expires_at"] = self._charge_expires_at.isoformat()
            remaining = self._charge_expires_at - datetime.now()
            if remaining.total_seconds() > 0:
                attrs["remaining_minutes"] = int(remaining.total_seconds() / 60)
            else:
                attrs["remaining_minutes"] = 0

        return attrs

    async def async_will_remove_from_hass(self) -> None:
        """Clean up when entity is removed."""
        if self._cancel_expiry_timer:
            self._cancel_expiry_timer()
            self._cancel_expiry_timer = None


# Ensure the following class is NOT nested inside another class/function.
class AdvancedBatteryControlSwitch(SwitchEntity):
    """Runtime toggle for Advanced battery control."""

    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        description: SwitchEntityDescription,
        suggested_object_id: str | None = None,
    ) -> None:
        self.hass = hass
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_suggested_object_id = suggested_object_id
        
        # Initialize state from config options
        from .const import CONF_ABC_ENABLED_DEFAULT, DEFAULT_ABC_ENABLED_DEFAULT
        self._attr_is_on = entry.options.get(
            SWITCH_TYPE_ADVANCED_BATTERY_CONTROL,
            entry.options.get(CONF_ABC_ENABLED_DEFAULT, DEFAULT_ABC_ENABLED_DEFAULT)
        )
        self._cancel_timer = None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes for observability."""
        attrs: dict[str, Any] = {}
        entry_data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        controller = entry_data.get(DATA_ABC_CONTROLLER)

        if controller:
            attrs.update({
                "state": controller.state.value if controller.state else None,
                "reason": controller.reason,
                "soc": controller.soc,
                "overnight_target_soc": controller.overnight_target_soc,
                "export_price": controller.export_price,
                "import_price": controller.import_price,
                "very_high_price_mode": controller.very_high_price_mode,
                "evening_peak_window": controller.evening_peak_window,
                "daytime_spike_allowed": controller.daytime_spike_allowed,
                "actual_mode": controller.actual_mode,
                "actual_backup": controller.actual_backup,
                "actual_grid_charging": controller.actual_grid_charging,
                "actual_export_rule": controller.actual_export_rule,
                "expected_export_rule": controller.expected_export_rule,
            })

        return attrs

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to Home Assistant."""
        if self._attr_is_on:
            _LOGGER.info("ABC: Resuming controller after restart")
            await self.async_turn_on(resuming=True)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable Advanced battery control."""
        resuming = kwargs.get("resuming", False)
        
        entry_data = self.hass.data.setdefault(DOMAIN, {}).setdefault(self._entry.entry_id, {})
        entry_data[DATA_ABC_ACTIVE] = True

        from .advanced_battery_control import AdvancedBatteryControlController

        controller = entry_data.get(DATA_ABC_CONTROLLER)
        if controller is None:
            controller = AdvancedBatteryControlController(self.hass, self._entry)
            entry_data[DATA_ABC_CONTROLLER] = controller

        await controller.async_start()

        if self._cancel_timer:
            self._cancel_timer()

        @callback
        def _tick(now: datetime) -> None:
            self.hass.async_create_task(controller.async_evaluate(reason="periodic"))

        self._cancel_timer = async_track_time_interval(self.hass, _tick, timedelta(seconds=30))

        self._attr_is_on = True
        
        if not resuming:
            # Persist state
            new_options = dict(self._entry.options)
            new_options[SWITCH_TYPE_ADVANCED_BATTERY_CONTROL] = True
            self.hass.config_entries.async_update_entry(self._entry, options=new_options)
            
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable Advanced battery control."""
        entry_data = self.hass.data.setdefault(DOMAIN, {}).setdefault(self._entry.entry_id, {})
        entry_data[DATA_ABC_ACTIVE] = False

        controller = entry_data.get(DATA_ABC_CONTROLLER)
        if controller is not None:
            try:
                await controller.async_stop()
            except Exception as err:
                _LOGGER.warning("Advanced battery control stop failed: %s", err)

        if self._cancel_timer:
            self._cancel_timer()
            self._cancel_timer = None

        self._attr_is_on = False
        
        # Persist state
        new_options = dict(self._entry.options)
        new_options[SWITCH_TYPE_ADVANCED_BATTERY_CONTROL] = False
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)
        
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Clean up when entity is removed."""
        if self._cancel_timer:
            self._cancel_timer()
            self._cancel_timer = None

class AdvancedBatteryControlGuardrailSwitch(SwitchEntity):
    """Switch to enable/disable Solcast guardrail for ABC."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:solar-power"

    def __init__(self, entry: ConfigEntry, suggested_object_id: str | None = None) -> None:
        self._entry = entry
        self._attr_name = "ABC Use Solcast Guardrail"
        self._attr_unique_id = f"{entry.entry_id}_abc_solcast_guardrail"
        self._attr_suggested_object_id = suggested_object_id

    @property
    def is_on(self) -> bool:
        """Return True if guardrail is enabled."""
        return bool(self._entry.options.get(CONF_ABC_USE_SOLCAST_GUARDRAIL, DEFAULT_ABC_USE_SOLCAST_GUARDRAIL))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        new_options = dict(self._entry.options)
        new_options[CONF_ABC_USE_SOLCAST_GUARDRAIL] = True
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        new_options = dict(self._entry.options)
        new_options[CONF_ABC_USE_SOLCAST_GUARDRAIL] = False
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)
        self.async_write_ha_state()
