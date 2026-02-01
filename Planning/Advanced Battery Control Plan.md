# PowerSync “Advanced battery control” Plan (Tesla Powerwall)

## TODO
- Check and reset Allow Charging from Grid and Allow Export.  With Smartswitch disabled, Amber seem to set these settings to stop battery control. ✓
- Check if there is a way to prevent Amber doing this (API permissions?), but allow it to read battery status.
- 

## 1) Summary

This document specifies a new **Advanced battery control** mode for the PowerSync integration, alongside the existing **TOU control** mode.

- **TOU control (standard mode):** PowerSync keeps the Powerwall’s TOU tariff schedule updated as it does today.
- **Advanced battery control (new mode):** PowerSync actively switches Powerwall operation mode between:
    - **Autonomous (TOU)** to allow exporting during profitable price events, and
    - **Self-Consumption** to stop exporting and power the home from battery so we don’t immediately buy at high import prices after the spike.

This mode is designed for Tesla Powerwall and must:
- Always maintain **20% minimum SOC** for emergency.
- **Charge from solar only** (no grid charging).
- Sell during evening peak until battery reaches an SOC level that supports the configured overnight load (350W) for the configured fixed night hours.
- If export price is **very high**, allow selling down to **40% SOC even if this jeopardises the overnight target**.
- Sell at **unexpected daytime peaks** only if solar forecast indicates we can still meet the minimum overnight charge (unless “very high” threshold is reached).
- Keep the **existing tariff sync logic** (TOU schedule updates) unchanged and still operating.
- Prevent clashes: while Advanced battery control is active, all other potentially conflicting “plans/features” must be effectively disabled (soft-disabled), so we don’t fight ourselves.

---

## 2) Goals and non-goals

### Goals
1. **Profit capture:** Export battery energy during high export price events (evening peaks and daytime spikes).
2. **Avoid expensive imports:** After selling, switch to Self-Consumption so the home runs off battery until prices stabilise.
3. **Safety floor:** Always preserve an emergency reserve of 20%.
4. **Solar-only charging:** Ensure grid charging is disabled.
5. **Forecast-aware daytime selling:** Use Solcast PV forecast as a guardrail so daytime selling doesn’t break overnight readiness (except in “very high” price mode).
6. **Operational simplicity:** A single on/off switch to enable/disable the Advanced logic.

### Non-goals
- Precise kW export control (Powerwall behaviour is influenced primarily via operation mode + tariffs; we do not implement direct setpoint export control).
- Replacing or redesigning the existing TOU tariff converter/sync pipeline. We keep it.
- Providing perfect “home load forecast” modelling. Overnight requirement is based on a fixed power target (350W) and fixed hours.

---

## 3) User-facing branding and controls

### 3.1 Two user-facing modes
- **TOU control** (existing):
    - Represents PowerSync’s standard tariff syncing behaviour.
    - Implemented as an existing switch (rename the entity display name accordingly).

- **Advanced battery control** (new):
    - Implemented as a new switch entity.
    - When enabled, it starts a periodic controller loop that manages operation mode and guardrails.

### 3.2 Switch behaviour (high level)
**TOU control (standard) switch**
- ON: existing tariff sync behaviour runs normally.
- OFF: tariff sync stops (as it does today).

**Advanced battery control switch**
- ON:
    - Start the Advanced control loop.
    - Enforce emergency reserve and solar-only charging.
    - Soft-disable conflicting features.
    - Operate in parallel with TOU control (TOU updates continue).

- OFF:
    - Stop the Advanced control loop.
    - Restore normal behaviour (typically return Powerwall to Autonomous unless user has manually set Self-Consumption; see “User manual override policy” below).
    - Re-enable (stop bypassing) conflicting features automatically (since we never changed their stored configuration; only bypassed them at runtime).

---

## 4) Core inputs and data sources

### 4.1 Real-time state (Tesla)
Required:
- Battery SOC (%)
- Grid power (kW), battery power (kW), solar power (kW), home load (kW) — for diagnostics and possible future refinement.

### 4.2 Pricing
Required:
- Current import price
- Current export price

These are already produced by the existing PowerSync provider coordinators.

### 4.3 Solar forecast (Solcast)
Required for daytime spike decisions:
- Remaining PV energy forecast for today (kWh) or equivalent.

If Solcast forecast is unavailable:
- Daytime spike selling should fail-safe (disable daytime spike selling) unless “very high” export price mode is active.

### 4.4 Battery capacity (Tesla)
Required:
- `battery_capacity_kwh` (or equivalent usable capacity).

We must obtain this from Tesla API (cached) rather than asking the user to type it.

Fallback policy:
- If capacity is not obtainable, Advanced battery control should still enforce:
    - emergency reserve 20%
    - solar-only charging
    - very-high-price selling floor (40%)
- But it should either:
    - disable the overnight-target logic (since it can’t compute), or
    - use a clearly documented conservative fallback (only if we can confidently determine Powerwall count).

---

## 5) Configuration (Options Flow)

All settings should live in `ConfigEntry.options` (like other features) and be editable in the integration’s configuration UI.

### 5.1 Advanced battery control settings (proposed)
Required / recommended:
- `abc_enabled_default` (bool, default false)  
  *Optional; actual runtime toggle is the switch, but this can decide default switch state on restart.*
- `abc_emergency_min_soc_percent` (int, default 20)
- `abc_high_price_min_soc_percent` (int, default 40)  
  *Hard floor during very high price mode.*
- `abc_overnight_load_w` (int, default 350)
- `abc_night_start` (HH:MM)
- `abc_night_end` (HH:MM)
- `abc_evening_peak_start` (HH:MM)
- `abc_evening_peak_end` (HH:MM)

Price thresholds:
- `abc_day_spike_export_threshold_cents` (float)  
  *Export price above this triggers daytime selling (forecast-guarded).*
- `abc_very_high_export_threshold_cents` (float)  
  *Export price above this triggers “risk mode” (ignore overnight target; allow down to 40%).*
- `abc_import_stabilised_threshold_cents` (float)  
  *If import is below this threshold, we consider prices “stabilised” and may exit buffer/self-consumption.*

Guardrails / hysteresis:
- `abc_use_solcast_guardrail` (bool, default true)
- `abc_buffer_min_minutes` (int, default e.g. 10)  
  *Minimum time to remain in buffer/self-consumption before switching back (reduces flapping).*
- `abc_mode_change_min_seconds` (int, default e.g. 60)  
  *Debounce for API calls; do not spam operation mode changes.*

### 5.2 Conflicting feature suppression (policy, not config)
When Advanced battery control is ON, treat the following as disabled at runtime:
- spike protection
- export price boost
- chip mode
- AEMO spike manager / spike tariff overrides
- any “force tariff mode toggle” behaviours that would fight our deliberate self_consumption switches
- other automated mode setters that could conflict

We should implement this as a **soft-disable**:
- Do not modify user config.
- Only bypass the logic while Advanced battery control is active.

---

## 6) Operating logic (state machine)

### 6.1 Definitions
- **Emergency floor:** `soc_emergency = 20%`
- **High-price floor:** `soc_high_price = 40%`
- **Night duration hours:** computed from fixed night start/end (handle crossing midnight).
- **Night kWh requirement:**
    - `night_kwh = (overnight_load_w / 1000) * night_hours`
- **Night SOC requirement (if capacity available):**
    - `soc_night = (night_kwh / battery_capacity_kwh) * 100`
- **Overnight target SOC (pre-night):**
    - `soc_overnight_target = soc_emergency + soc_night`
    - Clamp to `[soc_emergency, 100]`

### 6.2 States
- **NORMAL (Autonomous):** Default. TOU control runs. No special selling/buffering.
- **SELLING (Autonomous):** We want to export (sell) during a spike/peak.
- **BUFFER (Self-Consumption):** We stop exporting and run the home from battery to avoid high import prices after the spike.

### 6.3 Entry and exit conditions

#### 6.3.1 Very high export price mode (risk mode)
Condition:
- `export_price_cents >= abc_very_high_export_threshold_cents`

Actions:
1. Ensure grid charging disabled.
2. Ensure backup reserve set to 20%.
3. Set mode to **Autonomous** (SELLING) while `soc > 40%`.
4. When `soc <= 40%`, switch to **Self-Consumption** (BUFFER).

Important:
- In this mode, we explicitly allow selling down to 40% **even if it jeopardises overnight target**.

Exit from BUFFER:
- When import price is “stabilised” AND minimum buffer time elapsed:
    - set back to Autonomous (NORMAL).

#### 6.3.2 Evening peak selling
Condition:
- Current time within `[abc_evening_peak_start, abc_evening_peak_end)`
- (Optional: you may require export price above a minimal value; or “sell at whatever going price is” means no minimum. Default: no minimum.)

Actions:
1. Ensure grid charging disabled.
2. Ensure backup reserve set to 20%.
3. If SOC > overnight_target (and capacity is available):
    - set mode to Autonomous (SELLING)
4. If SOC <= overnight_target:
    - set mode to Self-Consumption (BUFFER)

Exit from BUFFER:
- When import price stabilises AND buffer_min_minutes elapsed, return to Autonomous (NORMAL).

Fallback if capacity unknown:
- Skip overnight_target logic and do not evening-sell (fail-safe), unless very high price mode is active.

#### 6.3.3 Daytime spike selling (forecast guarded)
Condition:
- `export_price_cents >= abc_day_spike_export_threshold_cents`
- and `abc_use_solcast_guardrail` is true
- and Solcast forecast indicates we can still meet overnight target after selling (capacity required)

Guardrail logic (conservative):
- Determine remaining PV kWh today from Solcast (`pv_remaining_kwh_today`).
- Convert to potential SOC replenishment:
    - `soc_recharge_possible = (pv_remaining_kwh_today / battery_capacity_kwh) * 100 * pv_to_battery_factor`
    - `pv_to_battery_factor` can be introduced later; default conservative like 0.5–0.7.
- Permit selling only if:
    - `soc_current + soc_recharge_possible >= soc_overnight_target`

Actions:
- If permitted:
    - Autonomous (SELLING) until SOC reaches `soc_overnight_target`, then Self-Consumption (BUFFER)
- If not permitted:
    - Self-Consumption (BUFFER) or remain NORMAL (Autonomous) depending on your preference; default: do not enter SELLING.

Fallback if Solcast unavailable:
- Do not daytime-sell unless very high price mode is active.

---

## 7) Control outputs (what we actually change)

### 7.1 Always-on guardrails while Advanced battery control is ON
- Set backup reserve to 20% (idempotent; avoid spamming calls).
- Disable grid charging (solar-only charging).

### 7.2 Primary behavioural lever
- Switch operation mode:
    - `autonomous` when we want to sell/export under tariff logic
    - `self_consumption` when we want to stop selling and ride out high import prices

### 7.3 Optional secondary lever (future)
- Grid export rules (`pv_only`, `battery_ok`, `never`) can further constrain behaviour, but per requirements we use operation mode to stop selling, not chip-mode or export-rule suppression. Consider only as a future enhancement.

---

## 8) “No clashes” implementation strategy

### 8.1 What counts as a clash?
Any other mechanism that may:
- modify the tariff schedule in a way that changes export behaviour unexpectedly
- set operation mode autonomously (e.g., spike handlers toggling to autonomous)
- enforce export suppression/boosts that conflict with the Advanced controller’s decisions

### 8.2 Soft-disable mechanism
When Advanced battery control is ON:
- Keep TOU tariff sync running.
- In the logic that applies:
    - spike protection
    - export boost
    - chip mode
    - AEMO spike behaviour
    - other export-related modifiers
- Treat them as disabled for this runtime session.

Implementation note:
- This should be checked in one place (a single “is_advanced_battery_control_active(entry_id)” helper) so it is consistent and easy to reason about.

---

## 9) User manual override policy (important UX detail)

We should define what happens if the user manually sets Self-Consumption in the Tesla app while Advanced battery control is OFF/ON.

Recommended:
- If Advanced battery control is ON:
    - We *do* set operation mode as needed (it is an active controller).
- If Advanced battery control is OFF:
    - We respect the user’s current mode and do not “force” changes, except whatever existing TOU sync already does today.

Optional enhancement:
- Store “last known mode before Advanced control took over” and restore it when turning Advanced OFF.

---

## 10) Observability (recommended sensors/attributes)

Add a status sensor (or attributes on the switch) to make it debuggable:

- Current controller state: `NORMAL | SELLING | BUFFER`
- Last decision reason (string)
- Current SOC
- Computed `soc_overnight_target` (if capacity available)
- Whether we are in:
    - “very high price mode”
    - “evening peak window”
    - “daytime spike allowed/blocked (forecast)”
- Last mode change timestamp
- Whether conflicting features are currently being bypassed

This prevents “it’s not working” mysteries.

---

## 11) Implementation steps (work breakdown)

### Phase 1 — Wiring + switch + guardrails
1. Add new switch entity: **Advanced battery control** ✓
2. Rename existing auto-sync switch display name to **TOU control** ✓
3. Add periodic loop that: ✓
    - enforces backup reserve = 20 ✓
    - enforces grid charging disabled ✓
    - enforces export allowed (battery_ok) to prevent Amber Smartswitch interference ✓
    - reads prices + SOC ✓
    - switches operation mode based on “very high” and “evening peak” rules (no Solcast yet) ✓

### Phase 2 — Daytime spike + Solcast guardrail
1. Read Solcast remaining kWh today ✓
2. Add daytime spike entry condition with guardrail ✓
3. Add fail-safe behaviour when forecast unavailable ✓

### Phase 3 — Clash prevention
1. Identify all logic branches that: ✓
    - modify tariffs (boost/chip/spike protection) ✓
    - toggle operation mode (AEMO spike handling etc.) ✓
2. Gate those branches behind: ✓
    - `if not advanced_battery_control_active: ...` ✓

### Phase 4 — Polish
1. Add status sensor/attributes ✓
2. Add debouncing (min seconds between mode changes) ✓
3. Improve buffer exit condition and add minimum buffer time ✓

---

## 12) Open decisions (to confirm during implementation)

1. **What defines “prices stabilised”?**
    - Proposed: import price < `abc_import_stabilised_threshold_cents` AND buffer_min_minutes elapsed.
2. **Should buffer exit also require leaving the evening window?**
    - Optional: prevents flip-flopping if evening window still active but import price briefly dips.
3. **PV-to-battery factor**
    - If we want conservative forecasting without detailed modelling, introduce a configurable factor (default 0.6).
4. **Capacity fetch endpoint**
    - Confirm the Tesla endpoint and field that reliably provides usable capacity in kWh across Teslemetry and Fleet API.
    - Cache it.

---

## 13) Acceptance criteria (definition of done)

1. When Advanced battery control is ON:
    - Backup reserve is held at 20%.
    - Grid charging remains disabled.
    - During very high export prices, the battery can sell down to 40% SOC and then stops selling by switching to Self-Consumption.
    - During evening peak, the battery sells until overnight target is met and then stops selling (Self-Consumption).
    - After selling stops, the house is powered from battery (buffer) until import prices stabilise.
    - Daytime spikes only trigger selling if Solcast forecast indicates overnight target can still be met (unless very high mode).
    - Other export-modifying features do not interfere (no clashes).

2. When Advanced battery control is OFF:
    - Advanced loop stops.
    - Existing TOU control continues to work normally (unchanged tariff sync behaviour).
    - Previously configured features resume normal operation (since they were only bypassed).

---

## 14) Glossary

- **TOU control:** PowerSync’s standard tariff sync behaviour.
- **Advanced battery control:** New active controller that switches operation mode to sell/hold intelligently.
- **Autonomous:** Powerwall Time-Based Control mode (uses TOU tariffs to decide charge/discharge/export).
- **Self-Consumption:** Powerwall mode that prioritises serving home load and reduces export behaviour.
- **Overnight target SOC:** SOC needed to supply 350W for configured night hours plus emergency reserve.
- **Buffer:** A Self-Consumption period after selling, intended to avoid expensive grid imports.