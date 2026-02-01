# custom_components/power_sync/advanced_battery_control.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import asyncio
import logging
from typing import Any, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    DATA_ABC_ACTIVE,
    DATA_ABC_CONTROLLER,
    CONF_ABC_EMERGENCY_MIN_SOC_PERCENT,
    CONF_ABC_HIGH_PRICE_MIN_SOC_PERCENT,
    CONF_ABC_OVERNIGHT_LOAD_W,
    CONF_ABC_EVENING_LOAD_W,
    CONF_ABC_NIGHT_START,
    CONF_ABC_NIGHT_END,
    CONF_ABC_EVENING_PEAK_START,
    CONF_ABC_EVENING_PEAK_END,
    CONF_ABC_DAY_SPIKE_EXPORT_THRESHOLD_CENTS,
    CONF_ABC_EXPORT_MIN_THRESHOLD_CENTS,
    CONF_ABC_VERY_HIGH_EXPORT_THRESHOLD_CENTS,
    CONF_ABC_IMPORT_STABILISED_THRESHOLD_CENTS,
    CONF_ABC_TRANSIENT_DURATION_MIN,
    CONF_ABC_USE_SOLCAST_GUARDRAIL,
    CONF_ABC_BUFFER_MIN_MINUTES,
    CONF_ABC_MODE_CHANGE_MIN_SECONDS,
    CONF_ABC_ENABLED_DEFAULT,
    DEFAULT_ABC_EMERGENCY_MIN_SOC_PERCENT,
    DEFAULT_ABC_HIGH_PRICE_MIN_SOC_PERCENT,
    DEFAULT_ABC_OVERNIGHT_LOAD_W,
    DEFAULT_ABC_EVENING_LOAD_W,
    DEFAULT_ABC_NIGHT_START,
    DEFAULT_ABC_NIGHT_END,
    DEFAULT_ABC_EVENING_PEAK_START,
    DEFAULT_ABC_EVENING_PEAK_END,
    DEFAULT_ABC_DAY_SPIKE_EXPORT_THRESHOLD_CENTS,
    DEFAULT_ABC_EXPORT_MIN_THRESHOLD_CENTS,
    DEFAULT_ABC_VERY_HIGH_EXPORT_THRESHOLD_CENTS,
    DEFAULT_ABC_IMPORT_STABILISED_THRESHOLD_CENTS,
    DEFAULT_ABC_TRANSIENT_DURATION_MIN,
    DEFAULT_ABC_USE_SOLCAST_GUARDRAIL,
    DEFAULT_ABC_BUFFER_MIN_MINUTES,
    DEFAULT_ABC_MODE_CHANGE_MIN_SECONDS,
    DEFAULT_ABC_ENABLED_DEFAULT,
    SERVICE_SET_BACKUP_RESERVE,
    SERVICE_SET_OPERATION_MODE,
    SERVICE_SET_GRID_CHARGING,
)
from .advanced_battery_control_types import ABCState

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ABCSettings:
    enabled_default: bool = DEFAULT_ABC_ENABLED_DEFAULT
    emergency_min_soc_percent: int = DEFAULT_ABC_EMERGENCY_MIN_SOC_PERCENT
    high_price_min_soc_percent: int = DEFAULT_ABC_HIGH_PRICE_MIN_SOC_PERCENT
    overnight_load_w: int = DEFAULT_ABC_OVERNIGHT_LOAD_W
    evening_load_w: int = DEFAULT_ABC_EVENING_LOAD_W

    night_start: str = DEFAULT_ABC_NIGHT_START
    night_end: str = DEFAULT_ABC_NIGHT_END

    evening_peak_start: str = DEFAULT_ABC_EVENING_PEAK_START
    evening_peak_end: str = DEFAULT_ABC_EVENING_PEAK_END

    day_spike_export_threshold_cents: float = DEFAULT_ABC_DAY_SPIKE_EXPORT_THRESHOLD_CENTS
    export_min_threshold_cents: float = DEFAULT_ABC_EXPORT_MIN_THRESHOLD_CENTS
    very_high_export_threshold_cents: float = DEFAULT_ABC_VERY_HIGH_EXPORT_THRESHOLD_CENTS
    import_stabilised_threshold_cents: float = DEFAULT_ABC_IMPORT_STABILISED_THRESHOLD_CENTS

    transient_duration_min: int = DEFAULT_ABC_TRANSIENT_DURATION_MIN
    use_solcast_guardrail: bool = DEFAULT_ABC_USE_SOLCAST_GUARDRAIL
    buffer_min_minutes: int = DEFAULT_ABC_BUFFER_MIN_MINUTES
    mode_change_min_seconds: int = DEFAULT_ABC_MODE_CHANGE_MIN_SECONDS

    @classmethod
    def from_entry(cls, entry: ConfigEntry) -> "ABCSettings":
        o = entry.options
        return cls(
            enabled_default=bool(o.get(CONF_ABC_ENABLED_DEFAULT, DEFAULT_ABC_ENABLED_DEFAULT)),
            emergency_min_soc_percent=int(o.get(CONF_ABC_EMERGENCY_MIN_SOC_PERCENT, DEFAULT_ABC_EMERGENCY_MIN_SOC_PERCENT)),
            high_price_min_soc_percent=int(o.get(CONF_ABC_HIGH_PRICE_MIN_SOC_PERCENT, DEFAULT_ABC_HIGH_PRICE_MIN_SOC_PERCENT)),
            overnight_load_w=int(o.get(CONF_ABC_OVERNIGHT_LOAD_W, DEFAULT_ABC_OVERNIGHT_LOAD_W)),
            evening_load_w=int(o.get(CONF_ABC_EVENING_LOAD_W, DEFAULT_ABC_EVENING_LOAD_W)),
            night_start=str(o.get(CONF_ABC_NIGHT_START, DEFAULT_ABC_NIGHT_START)),
            night_end=str(o.get(CONF_ABC_NIGHT_END, DEFAULT_ABC_NIGHT_END)),
            evening_peak_start=str(o.get(CONF_ABC_EVENING_PEAK_START, DEFAULT_ABC_EVENING_PEAK_START)),
            evening_peak_end=str(o.get(CONF_ABC_EVENING_PEAK_END, DEFAULT_ABC_EVENING_PEAK_END)),
            day_spike_export_threshold_cents=float(o.get(CONF_ABC_DAY_SPIKE_EXPORT_THRESHOLD_CENTS, DEFAULT_ABC_DAY_SPIKE_EXPORT_THRESHOLD_CENTS)),
            export_min_threshold_cents=float(o.get(CONF_ABC_EXPORT_MIN_THRESHOLD_CENTS, DEFAULT_ABC_EXPORT_MIN_THRESHOLD_CENTS)),
            very_high_export_threshold_cents=float(o.get(CONF_ABC_VERY_HIGH_EXPORT_THRESHOLD_CENTS, DEFAULT_ABC_VERY_HIGH_EXPORT_THRESHOLD_CENTS)),
            import_stabilised_threshold_cents=float(o.get(CONF_ABC_IMPORT_STABILISED_THRESHOLD_CENTS, DEFAULT_ABC_IMPORT_STABILISED_THRESHOLD_CENTS)),
            transient_duration_min=int(o.get(CONF_ABC_TRANSIENT_DURATION_MIN, DEFAULT_ABC_TRANSIENT_DURATION_MIN)),
            use_solcast_guardrail=bool(o.get(CONF_ABC_USE_SOLCAST_GUARDRAIL, DEFAULT_ABC_USE_SOLCAST_GUARDRAIL)),
            buffer_min_minutes=int(o.get(CONF_ABC_BUFFER_MIN_MINUTES, DEFAULT_ABC_BUFFER_MIN_MINUTES)),
            mode_change_min_seconds=int(o.get(CONF_ABC_MODE_CHANGE_MIN_SECONDS, DEFAULT_ABC_MODE_CHANGE_MIN_SECONDS)),
        )


def is_advanced_battery_control_active(hass: HomeAssistant, entry_id: str) -> bool:
    """Single source of truth for runtime gating (soft-disable conflicting features)."""
    return bool(hass.data.get(DOMAIN, {}).get(entry_id, {}).get(DATA_ABC_ACTIVE, False))


class AdvancedBatteryControlController:
    """Framework controller for Advanced battery control.

    This class owns the evaluation cadence and implements the state machine
    (SELLING / BUFFER / NORMAL).
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.state = ABCState.NORMAL
        self.reason = "Initialised"
        self._last_mode_change: datetime | None = None
        self._last_buffer_entered: datetime | None = None

        # Attributes for observability
        self.overnight_target_soc: float | None = None
        self.very_high_price_mode: bool = False
        self.evening_peak_window: bool = False
        self.daytime_spike_allowed: bool = False
        self.soc: float | None = None
        self.export_price: float | None = None
        self.import_price: float | None = None

        # Audited hardware settings
        self.actual_mode: str | None = None
        self.actual_backup: int | None = None
        self.actual_grid_charging: bool | None = None
        self.actual_export_rule: str | None = None
        self.expected_export_rule: str = "battery_ok"

    def _get_settings(self) -> ABCSettings:
        return ABCSettings.from_entry(self.entry)

    async def async_start(self) -> None:
        """Called when the Advanced battery control switch turns on."""
        _LOGGER.info("Advanced battery control: starting controller")
        self.reason = "Controller started"
        await self.async_evaluate(reason="startup")

    async def async_stop(self) -> None:
        """Called when the Advanced battery control switch turns off."""
        _LOGGER.info("Advanced battery control: stopping controller")
        self.reason = "Controller stopped"
        # Restore normal mode policy: return to autonomous
        current_mode = await self._get_current_tesla_operation_mode()
        if current_mode != "autonomous":
            _LOGGER.info("ABC: [Hardware] Restoring Tesla mode on stop: %s -> autonomous", current_mode or "unknown")
            await self._set_tesla_operation_mode("autonomous")
        else:
            _LOGGER.debug("ABC: [Hardware] Tesla mode already autonomous on stop, skipping")

    async def async_evaluate(self, reason: str = "periodic") -> None:
        """Single evaluation tick (implements the state machine)."""
        settings = self._get_settings()
        now = dt_util.now()

        _LOGGER.debug("ABC: --- Evaluation Loop Start (%s) ---", reason)

        # 1. Hardware Audit (BEFORE)
        actual_before = await self._fetch_hardware_config()
        self._log_hardware_audit_table("BEFORE Update", actual_before, settings, self.state)

        # 2. Fetch sensor data
        self.soc = self._read_battery_soc_percent()
        self.export_price = self._read_current_export_price_cents()
        self.import_price = self._read_current_import_price_cents()
        capacity = self._read_battery_capacity_kwh()
        pv_remaining = self._read_pv_remaining_kwh()
        detailed_forecast = self._read_detailed_pv_forecast()
        current_load_w = self._read_home_load_w()

        if self.soc is None or self.export_price is None or self.import_price is None:
            self.reason = "Waiting for data (SOC/Price)"
            _LOGGER.debug("ABC: [Data] Missing data - soc: %s, export: %s, import: %s", self.soc, self.export_price, self.import_price)
            return

        _LOGGER.debug("ABC: [Data] SOC: %s%%, Export: %s¢, Import: %s¢", self.soc, self.export_price, self.import_price)

        # 3. Compute targets
        self.overnight_target_soc = self._compute_overnight_target(settings, capacity, detailed_forecast, current_load_w)
        self.very_high_price_mode = self.export_price >= settings.very_high_export_threshold_cents
        self.evening_peak_window = self._is_in_window(now, settings.evening_peak_start, settings.evening_peak_end)
        
        # Determine expected export rule (suppress if below threshold)
        self.expected_export_rule = "battery_ok"
        if self.export_price < settings.export_min_threshold_cents:
            self.expected_export_rule = "never"
            _LOGGER.debug("ABC: [Logic] Export cost detected (Earnings: %s¢ < Threshold: %s¢) - setting rule to 'never'", 
                         self.export_price, settings.export_min_threshold_cents)

        # Daytime spike allowed logic
        self.daytime_spike_allowed = False
        if not self.evening_peak_window and self.export_price >= settings.day_spike_export_threshold_cents:
            if settings.use_solcast_guardrail:
                if pv_remaining is not None and capacity is not None and self.overnight_target_soc is not None:
                    # Permit selling only if current SOC + potential recharge >= target
                    # Using a conservative 0.6 factor for PV-to-battery efficiency
                    soc_recharge_possible = (pv_remaining / capacity) * 100.0 * 0.6
                    if self.soc + soc_recharge_possible >= self.overnight_target_soc:
                        self.daytime_spike_allowed = True
                        _LOGGER.debug("ABC: [Logic] Daytime spike allowed (forecast recharge: %s%%)", soc_recharge_possible)
                    else:
                        _LOGGER.debug("ABC: [Logic] Daytime spike BLOCKED by Solcast guardrail (recharge: %s%%, need: %s%%)", 
                                     soc_recharge_possible, self.overnight_target_soc - self.soc)
                else:
                    _LOGGER.debug("ABC: [Logic] Solcast guardrail enabled but data missing")
            else:
                self.daytime_spike_allowed = True

        # 4. State Machine Logic
        new_state = ABCState.NORMAL
        eval_reason = "Normal operation"

        # Priority 0: Export cost suppression (Highest priority - stop exporting if it costs money)
        if self.expected_export_rule == "never":
            new_state = ABCState.BUFFER
            eval_reason = f"Export cost detected ({self.export_price}c) - forcing BUFFER and disabling export"

        # Priority 1: Very High Price (Risk Mode)
        elif self.very_high_price_mode:
            if self.soc > 40:
                new_state = ABCState.SELLING
                eval_reason = f"Very high price ({self.export_price}c) > 40% SOC"
            else:
                new_state = ABCState.BUFFER
                eval_reason = f"Very high price but SOC ({self.soc}%) <= 40%"
        
        # Priority 2: Evening Peak Window
        elif self.evening_peak_window:
            if self.overnight_target_soc is not None:
                if self.soc > self.overnight_target_soc:
                    new_state = ABCState.SELLING
                    eval_reason = f"Evening peak & SOC ({self.soc}%) > target ({self.overnight_target_soc}%)"
                else:
                    new_state = ABCState.BUFFER
                    eval_reason = f"Evening peak & SOC ({self.soc}%) <= target ({self.overnight_target_soc}%)"
            else:
                eval_reason = "Evening peak but capacity unknown - fail safe"
        
        # Priority 3: Daytime Spike (Forecast Guarded)
        elif self.daytime_spike_allowed:
            if self.overnight_target_soc is not None and self.soc > self.overnight_target_soc:
                new_state = ABCState.SELLING
                eval_reason = f"Daytime spike & SOC ({self.soc}%) > target ({self.overnight_target_soc}%)"
            else:
                new_state = ABCState.BUFFER
                eval_reason = f"Daytime spike & SOC ({self.soc}%) <= target ({self.overnight_target_soc}%)"
        
        # Priority 4: Post-Spike Buffer (Ride out high import prices after a spike)
        elif self.state in (ABCState.SELLING, ABCState.BUFFER):
            price_high = self.import_price > settings.import_stabilised_threshold_cents
            
            if price_high:
                new_state = ABCState.BUFFER
                eval_reason = f"Spike ended, entering/holding BUFFER: Import ({self.import_price}c) > threshold ({settings.import_stabilised_threshold_cents}c)"
            elif self.state == ABCState.BUFFER:
                # We are already in BUFFER, check min time
                elapsed_m = 0.0
                if self._last_buffer_entered:
                    elapsed_m = (now - self._last_buffer_entered).total_seconds() / 60.0
                
                if elapsed_m < settings.buffer_min_minutes:
                    new_state = ABCState.BUFFER
                    eval_reason = f"Holding BUFFER: Min duration ({round(elapsed_m, 1)}m < {settings.buffer_min_minutes}m)"

        # 5. Apply Actions
        changes_made = await self._apply_state(new_state, eval_reason)
        changes_made |= await self._enforce_guardrails(settings)

        # 6. Verification Audit (AFTER)
        if changes_made:
            _LOGGER.debug("ABC: [Hardware] Changes applied, waiting 5s for propagation...")
            await asyncio.sleep(5)
        
        actual_after = await self._fetch_hardware_config()
        self._log_hardware_audit_table("AFTER Update", actual_after, settings, self.state)

        _LOGGER.debug("ABC: --- Evaluation Loop End ---")

    async def _apply_state(self, new_state: ABCState, reason: str) -> bool:
        """Apply the decided state to the hardware. Returns True if changes were sent."""
        changes_attempted = False
        if new_state != self.state:
            _LOGGER.info("ABC: [State Change] %s -> %s (Reason: %s)", self.state, new_state, reason)
            self.state = new_state
            self._last_mode_change = dt_util.now()
            if new_state == ABCState.BUFFER:
                self._last_buffer_entered = dt_util.now()
        else:
            _LOGGER.debug("ABC: [State] Holding %s (Reason: %s)", self.state, reason)

        self.reason = reason

        # Determine desired Tesla mode
        desired_mode = "autonomous"
        if self.state == ABCState.BUFFER:
            desired_mode = "self_consumption"

        # Check current Tesla mode before applying (using cached info if available for efficiency)
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        tesla_coord = entry_data.get("tesla_coordinator")
        current_mode = None
        if tesla_coord and tesla_coord._site_info_cache:
            current_mode = tesla_coord._site_info_cache.get("default_real_mode")

        if current_mode == desired_mode:
            _LOGGER.debug("ABC: [Hardware] Tesla mode already %s, skipping", desired_mode)
        else:
            _LOGGER.info("ABC: [Hardware] Changing Tesla mode: %s -> %s", current_mode or "unknown", desired_mode)
            await self._set_tesla_operation_mode(desired_mode)
            changes_attempted = True
        
        return changes_attempted

    async def _get_current_tesla_operation_mode(self) -> Optional[str]:
        """Fetch the current Tesla operation mode from the coordinator."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        tesla_coord = entry_data.get("tesla_coordinator")
        if not tesla_coord:
            return None

        site_info = await tesla_coord.async_get_site_info()
        if site_info:
            return site_info.get("default_real_mode")
        return None

    async def _enforce_guardrails(self, settings: ABCSettings) -> bool:
        """Enforce always-on guardrails (Backup reserve, solar-only charging, export rule). Returns True if changes sent."""
        _LOGGER.debug("ABC: [Guardrails] Checking battery safety settings")
        
        # 0. Get current site config to check for overrides
        current_export_rule = None
        current_backup_reserve = None
        current_grid_charging_disallowed = None

        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        tesla_coord = entry_data.get("tesla_coordinator")
        if not tesla_coord:
            return False

        # Use cache for initial check to avoid unnecessary API pressure
        site_info = tesla_coord._site_info_cache
        if site_info:
            current_backup_reserve = site_info.get("backup_reserve_percent")
            
            components = site_info.get("components", {})
            battery_config = site_info.get("battery_config", {})
            
            # Robust grid charging extraction
            current_grid_charging_disallowed = components.get("disallow_charge_from_grid_with_solar_installed")
            if current_grid_charging_disallowed is None:
                current_grid_charging_disallowed = site_info.get("disallow_charge_from_grid_with_solar_installed")
            if current_grid_charging_disallowed is None:
                current_grid_charging_disallowed = battery_config.get("disallow_charge_from_grid_with_solar_installed")

            # Robust export rule extraction
            current_export_rule = components.get("customer_preferred_export_rule")
            if current_export_rule is None:
                current_export_rule = site_info.get("customer_preferred_export_rule")
            if current_export_rule is None:
                current_export_rule = battery_config.get("customer_preferred_export_rule")

        corrections_applied = False

        # 1. Backup Reserve
        if current_backup_reserve is not None and current_backup_reserve != settings.emergency_min_soc_percent:
            _LOGGER.info("ABC: [Hardware] Changing Backup Reserve: %s%% -> %s%% (Amber Override 🛡️)", current_backup_reserve, settings.emergency_min_soc_percent)
            corrections_applied = True
            try:
                await self.hass.services.async_call(
                    DOMAIN,
                    SERVICE_SET_BACKUP_RESERVE,
                    {"percent": settings.emergency_min_soc_percent},
                    blocking=True,
                )
            except Exception as err:
                _LOGGER.warning("ABC: [Guardrails] Failed to enforce backup reserve: %s", err)

        # 2. Grid Charging (Solar-only)
        # Fix: Try to enforce if NOT explicitly Disabled (True), even if None/Unknown
        if current_grid_charging_disallowed != True: 
            _LOGGER.info("ABC: [Hardware] Changing Grid Charging: %s -> Disabled (Solar-only) (Amber Override 🔌)", 
                         "Enabled" if current_grid_charging_disallowed == False else "Unknown")
            corrections_applied = True
            try:
                await self.hass.services.async_call(
                    DOMAIN,
                    SERVICE_SET_GRID_CHARGING,
                    {"enabled": False},
                    blocking=True,
                )
            except Exception as err:
                _LOGGER.warning("ABC: [Guardrails] Failed to enforce solar-only charging: %s", err)

        # 3. Export Rule (Allow Export / Disable when paying)
        # Fix: Try to enforce if doesn't match expected, even if None/Unknown
        if current_export_rule != self.expected_export_rule:
            _LOGGER.info("ABC: [Hardware] Changing Grid Export Rule: %s -> %s (Amber Override ⚡)", 
                         current_export_rule or "Unknown", self.expected_export_rule)
            corrections_applied = True
            try:
                await self.hass.services.async_call(
                    DOMAIN,
                    "set_grid_export",
                    {"rule": self.expected_export_rule},
                    blocking=True,
                )
            except Exception as err:
                _LOGGER.warning("ABC: [Guardrails] Failed to enforce export rule: %s", err)

        return corrections_applied

    def _compute_overnight_target(self, settings: ABCSettings, capacity: Optional[float], detailed_forecast: Optional[list[dict]] = None, current_load_w: Optional[float] = None) -> Optional[float]:
        """Compute the SOC required to meet predicted load until sunrise."""
        if capacity is None or capacity <= 0:
            return None

        now = dt_util.now()
        
        # 1. Determine the target Sunrise (Night End)
        end_dt = None
        try:
            fixed_end_time = datetime.strptime(settings.night_end, "%H:%M").time()
        except ValueError:
            _LOGGER.warning("ABC: Invalid night end time format")
            return None

        # Try to find dynamic sunrise from Solcast
        if detailed_forecast:
            load_kw = settings.overnight_load_w / 1000.0
            for period in detailed_forecast:
                try:
                    p_end_str = period.get("period_end")
                    p_estimate = period.get("pv_estimate")
                    if p_end_str and p_estimate is not None:
                        p_end_local = datetime.fromisoformat(p_end_str)
                        if 4 <= p_end_local.hour <= 11 and p_end_local > now and p_estimate > load_kw:
                            end_dt = p_end_local
                            _LOGGER.info("ABC: [Logic] Dynamic sunrise from Solcast: %s (Solar > %skW)", 
                                         end_dt.strftime("%Y-%m-%d %H:%M"), round(load_kw, 2))
                            break
                except (ValueError, TypeError):
                    continue
        
        if end_dt is None:
            # Fallback to tomorrow morning at fixed night end
            end_dt = now.replace(hour=fixed_end_time.hour, minute=fixed_end_time.minute, second=0, microsecond=0)
            # Ensure it is in the future
            if end_dt <= now:
                end_dt += timedelta(days=1)
            _LOGGER.debug("ABC: [Logic] Using fixed night end: %s", end_dt.strftime("%Y-%m-%d %H:%M"))

        # 2. Determine Night Start
        try:
            start_time_obj = datetime.strptime(settings.night_start, "%H:%M").time()
        except ValueError:
            _LOGGER.warning("ABC: Invalid night start time format")
            return None

        # Find the occurrence of Night Start associated with this sunrise
        # It's the most recent Night Start before end_dt
        start_dt = end_dt.replace(hour=start_time_obj.hour, minute=start_time_obj.minute, second=0, microsecond=0)
        if start_dt >= end_dt:
            start_dt -= timedelta(days=1)

        # 3. Energy Calculation (Active vs Sleep)
        total_energy_kwh = 0.0
        
        # --- Sleep Phase (Night Start until Sunrise) ---
        # Energy needed for the entire sleep window
        sleep_duration = (end_dt - start_dt).total_seconds() / 3600
        # If we are currently in the sleep window, only count remaining hours
        remaining_sleep_duration = max(0.0, (end_dt - max(now, start_dt)).total_seconds() / 3600)
        total_energy_kwh += (settings.overnight_load_w / 1000.0) * remaining_sleep_duration

        # --- Active Phase (Now until Night Start) ---
        if now < start_dt:
            active_duration = (start_dt - now).total_seconds() / 3600
            
            # Baseline evening energy
            baseline_energy = (settings.evening_load_w / 1000.0) * active_duration
            
            # Rolling Transient Buffer for cooking spikes
            transient_energy = 0.0
            if current_load_w is not None and current_load_w > settings.evening_load_w:
                excess_w = current_load_w - settings.evening_load_w
                # Project excess for 1 hour (or until night start)
                transient_hours = min(active_duration, settings.transient_duration_min / 60.0)
                transient_energy = (excess_w / 1000.0) * transient_hours
                _LOGGER.debug("ABC: [Logic] Adding transient buffer: %sW for %sh", round(excess_w, 0), round(transient_hours, 2))
            
            total_energy_kwh += (baseline_energy + transient_energy)

        # 4. Final SOC Target
        soc_needed = (total_energy_kwh / capacity) * 100.0
        target = settings.emergency_min_soc_percent + soc_needed
        
        # Diagnostics
        _LOGGER.debug("ABC: [Logic] Target breakdown - Sleep: %sh (%sW), Active: %skWh, Total: %skWh, SOC: %s%% (+%s%% emergency)",
                     round(remaining_sleep_duration, 1), settings.overnight_load_w, 
                     round(total_energy_kwh - (settings.overnight_load_w/1000*remaining_sleep_duration), 2),
                     round(total_energy_kwh, 2), round(target, 1), settings.emergency_min_soc_percent)

        return min(max(target, float(settings.emergency_min_soc_percent)), 100.0)

    def _is_in_window(self, now: datetime, start_str: str, end_str: str) -> bool:
        """Check if current time is within HH:MM window."""
        try:
            start_time = datetime.strptime(start_str, "%H:%M").time()
            end_time = datetime.strptime(end_str, "%H:%M").time()
            current_time = now.time()

            if start_time <= end_time:
                return start_time <= current_time < end_time
            else: # Crosses midnight
                return current_time >= start_time or current_time < end_time
        except ValueError:
            return False

    async def _set_tesla_operation_mode(self, mode: str) -> None:
        """Call Tesla service to set operation mode."""
        try:
            await self.hass.services.async_call(
                DOMAIN,
                SERVICE_SET_OPERATION_MODE,
                {"mode": mode},
                blocking=True,
            )
        except Exception as err:
            _LOGGER.warning("ABC: [Hardware] Failed to set operation mode to %s: %s", mode, err)

    async def _fetch_hardware_config(self) -> dict[str, Any]:
        """Fetch fresh hardware configuration from Tesla API."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        tesla_coord = entry_data.get("tesla_coordinator")
        if not tesla_coord:
            return {}

        # Force refresh site info from API (clear cache)
        tesla_coord._site_info_cache = None
        site_info = await tesla_coord.async_get_site_info()
        
        if not site_info:
            return {}

        components = site_info.get("components", {})
        battery_config = site_info.get("battery_config", {})
        
        # Robust grid charging extraction
        grid_charging = components.get("disallow_charge_from_grid_with_solar_installed")
        if grid_charging is None:
            grid_charging = site_info.get("disallow_charge_from_grid_with_solar_installed")
        if grid_charging is None:
            grid_charging = battery_config.get("disallow_charge_from_grid_with_solar_installed")

        # Robust export rule extraction
        export_rule = components.get("customer_preferred_export_rule")
        if export_rule is None:
            export_rule = site_info.get("customer_preferred_export_rule")
        if export_rule is None:
            export_rule = battery_config.get("customer_preferred_export_rule")

        # Diagnostic logging if still missing
        if grid_charging is None or export_rule is None:
            _LOGGER.debug("ABC: [Hardware] Missing settings in site_info. Keys: %s, Components: %s, BatteryConfig: %s", 
                         list(site_info.keys()), list(components.keys()) if components else "N/A", 
                         list(battery_config.keys()) if battery_config else "N/A")

        config = {
            "mode": site_info.get("default_real_mode"),
            "backup": site_info.get("backup_reserve_percent"),
            "grid_charging": grid_charging, # True = Disabled
            "export_rule": export_rule
        }

        # Store for observability
        self.actual_mode = config["mode"]
        self.actual_backup = config["backup"]
        self.actual_grid_charging = config["grid_charging"]
        self.actual_export_rule = config["export_rule"]

        return config

    def _log_hardware_audit_table(self, label: str, actual: dict[str, Any], settings: ABCSettings, state: ABCState) -> None:
        """Log a comparison table of hardware settings."""
        # Determine expected
        expected_mode = "self_consumption" if state == ABCState.BUFFER else "autonomous"
        expected_grid_charging = True # We want it Disabled (disallow=True)
        expected_export = self.expected_export_rule
        expected_backup = settings.emergency_min_soc_percent

        # Format strings for display
        def fmt_gc(val):
            if val is None: return "Unknown"
            return "Disabled" if val else "Enabled"

        def get_status(actual_val, expected_val):
            return "✅" if actual_val == expected_val else "❌"

        # Special check for grid charging because True = Disabled
        gc_status = "✅" if actual.get("grid_charging") is True else "❌"

        # Build table
        table = [
            f"ABC: [Hardware Audit] {label}",
            f"{'Setting':<20} | {'Actual':<15} | {'Expected':<15} | {'Status'}",
            f"{'-'*20}-|-{'-'*15}-|-{'-'*15}-|-{'-'*6}",
            f"{'Operation Mode':<20} | {str(actual.get('mode')):<15} | {expected_mode:<15} | {get_status(actual.get('mode'), expected_mode)}",
            f"{'Backup Reserve':<20} | {str(actual.get('backup')) + '%':<15} | {str(expected_backup) + '%':<15} | {get_status(actual.get('backup'), expected_backup)}",
            f"{'Grid Charging':<20} | {fmt_gc(actual.get('grid_charging')):<15} | {'Disabled':<15} | {gc_status}",
            f"{'Grid Export Rule':<20} | {str(actual.get('export_rule')):<15} | {expected_export:<15} | {get_status(actual.get('export_rule'), expected_export)}"
        ]
        
        # Use INFO level if there are ❌ or for the AFTER label
        has_error = any("❌" in line for line in table)
        log_msg = "\n" + "\n".join(table)
        if has_error or "AFTER" in label:
            _LOGGER.info(log_msg)
        else:
            _LOGGER.debug(log_msg)

    def _read_battery_soc_percent(self) -> Optional[float]:
        """Read SOC from the Tesla energy coordinator data."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        tesla_coord = entry_data.get("tesla_coordinator")
        data = getattr(tesla_coord, "data", None) if tesla_coord else None
        if not isinstance(data, dict):
            return None
        value = data.get("battery_level")
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _read_battery_capacity_kwh(self) -> Optional[float]:
        """Read usable battery capacity in kWh."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        tesla_coord = entry_data.get("tesla_coordinator")
        
        # Try to get it from site_info first
        if tesla_coord:
            # We use a protected member access here for troubleshooting
            site_info = getattr(tesla_coord, "_site_info_cache", None)
            if site_info:
                # Nominal capacity is often in nominal_system_energy_kwh
                # or we can try to find it in the response
                cap = site_info.get("nominal_system_energy_kwh")
                if cap:
                    return float(cap)
        
        # Fallback to 13.5 (single PW2) if not found
        return 13.5

    def _read_pv_remaining_kwh(self) -> Optional[float]:
        """Read remaining PV forecast for today (kWh)."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        solcast_coord = entry_data.get("solcast_coordinator")
        data = getattr(solcast_coord, "data", None) if solcast_coord else None
        if not isinstance(data, dict):
            return None
        return data.get("today_remaining_kwh")

    def _read_detailed_pv_forecast(self) -> Optional[list[dict]]:
        """Read detailed PV forecast periods."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        solcast_coord = entry_data.get("solcast_coordinator")
        data = getattr(solcast_coord, "data", None) if solcast_coord else None
        if not isinstance(data, dict):
            return None
        return data.get("detailed_forecast")

    def _read_current_export_price_cents(self) -> Optional[float]:
        """Read current export price (c/kWh)."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        # The price coordinator is stored as amber_coordinator or aemo_sensor_coordinator
        price_coord = entry_data.get("amber_coordinator") or entry_data.get("aemo_sensor_coordinator")
        data = getattr(price_coord, "data", None) if price_coord else None
        if not isinstance(data, dict) or not data.get("current"):
            return None

        # Amber logic
        for price in data.get("current", []):
            if price.get("channelType") == "feedIn":
                # Amber perKwh is negative for earnings. We return cents.
                # e.g. -15.0 -> 15.0c
                return -float(price.get("perKwh", 0))
        return None

    def _read_current_import_price_cents(self) -> Optional[float]:
        """Read current import price (c/kWh)."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        price_coord = entry_data.get("amber_coordinator") or entry_data.get("aemo_sensor_coordinator")
        data = getattr(price_coord, "data", None) if price_coord else None
        if not isinstance(data, dict) or not data.get("current"):
            return None

        for price in data.get("current", []):
            if price.get("channelType") == "general":
                return float(price.get("perKwh", 0))
        return None

    def _read_home_load_w(self) -> Optional[float]:
        """Read current home load in Watts."""
        entry_data = self.hass.data.get(DOMAIN, {}).get(self.entry.entry_id, {})
        tesla_coord = entry_data.get("tesla_coordinator")
        data = getattr(tesla_coord, "data", None) if tesla_coord else None
        if not isinstance(data, dict):
            return None
        # Tesla coordinator stores 'load_power' in kW
        value = data.get("load_power")
        try:
            return float(value) * 1000.0 if value is not None else None
        except (TypeError, ValueError):
            return None