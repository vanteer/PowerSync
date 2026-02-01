# Advanced Battery Control (ABC)

Advanced Battery Control is an intelligent state machine designed for Tesla Powerwall users. It actively manages the battery's operation mode to maximize export profits during price spikes while ensuring enough energy is reserved to power the home until sunrise.

## 1. Core Logic & States

The ABC system operates in three primary states, evaluated every 30 seconds:

*   **NORMAL (Autonomous)**: The default state. The Powerwall follows its standard Time-Based Control (TOU) logic using the tariffs synced by PowerSync.
*   **SELLING (Autonomous)**: Triggered when prices are high. The system ensures the battery is in a state that allows exporting to the grid.
*   **BUFFER (Self-Consumption)**: Triggered when the battery reaches its "reserved" level or when a price spike ends while import prices remain high. It switches to Self-Consumption mode to stop exporting and prioritize powering the home, riding out high import prices until they stabilize. This "Sticky BUFFER" logic prevents expensive imports during the volatile period immediately following a spike.

### Operational Summary

| Feature / Guardrail | NORMAL | SELLING | BUFFER |
| :--- | :--- | :--- | :--- |
| **Tesla Operation Mode** | `autonomous` | `autonomous` | `self_consumption` |
| **Backup Reserve** | Enforced | Enforced | Enforced |
| **Grid Charging** | Disabled | Disabled | Disabled |
| **Export Rule** | `battery_ok` | `battery_ok` | `battery_ok` |
| **Tariff Syncing** | Active | Active | Active |
| **Feature Suppression** | Active | Active | Active |

## 2. Predictive Energy Model

The most critical feature of ABC is its ability to calculate exactly how much energy you need to keep in the battery ("Overnight Target SOC").

### Dynamic Sunrise Tracking
Instead of using a fixed clock time, ABC uses the **Solcast PV Forecast** to identify the exact moment tomorrow morning when solar generation will exceed your home load. This "Dynamic Night End" ensures you don't hold unnecessary energy on sunny mornings but stay protected during dark winter days.

### Two-Phase Reservation
ABC splits the remaining time until sunrise into two phases:
1.  **Active Phase (Now until Night Start)**: Uses a higher "Evening Load" baseline.
2.  **Sleep Phase (Night Start until Sunrise)**: Uses a lower "Overnight Load" baseline.

### Rolling Transient Buffer
To account for unpredictable cooking spikes (ovens, microwaves, etc.) without over-reserving for the entire night, ABC implements a **1-hour rolling buffer**. If your current home load exceeds the evening baseline, the excess is projected forward for only one hour. As soon as the appliance is turned off, the target SOC drops, potentially freeing up more energy for profit.

## 3. Selling Strategies & Stabilization

ABC identifies four types of profitable or cost-avoiding events:

*   **Export Cost Suppression**: If export earnings fall below the `Export Minimum Earnings` threshold (default 0¢), the system immediately sets the Grid Export Rule to **never** and forces the battery into **BUFFER** mode. This protects you from paying to export energy during negative price events.
*   **Very High Price (Risk Mode)**: Triggered when export prices exceed the `Very High Export Threshold`. In this mode, the system will sell down to **40% SOC**, even if it jeopardizes the overnight target, to capture extreme profits.
*   **Evening Peak Selling**: Occurs during the configured evening window. The system sells battery energy down until the **Overnight Target SOC** is reached, then switches to BUFFER mode.
*   **Daytime Spike (Forecast Guarded)**: Allows selling during unexpected daytime spikes only if the Solcast forecast confirms there is enough solar energy remaining today to recharge the battery to its overnight target before evening.

### 3.4 Post-Spike Stabilization (Sticky BUFFER)
To prevent the battery from returning to standard TOU control while grid prices are still high or volatile, ABC implements a stabilization phase. After any selling event or price spike, the controller will hold the battery in **BUFFER (Self-Consumption)** mode until:
1.  **Prices Stabilize**: The current import price drops below the `Import Stabilised Threshold`.
2.  **Minimum Duration**: The battery has remained in BUFFER mode for at least the `Min Buffer Time` (default 10 minutes).

## 4. Hardware Guardrails & Reliability

ABC includes robust "Anti-Interference" logic to ensure it remains in control even if external providers (like Amber Smartswitch) try to override settings.

### Global Guardrails
Whenever ABC is ON, it enforces the following every 30 seconds:
*   **Backup Reserve**: Locked to your `Emergency Min SOC` (default 20%).
*   **Grid Charging**: Forced to **Disabled** (Solar-only charging).
*   **Grid Export Rule**: Forced to **Allow Export** (`battery_ok`).
*   **Conflicting Feature Suppression**: Standard PowerSync features like Spike Protection, Export Boost, Chip Mode, and AEMO Spike Manager are automatically bypassed while ABC is active to prevent control conflicts.

### Verification Logic
Every time ABC changes a hardware setting (Operation Mode, Export Rule, etc.), it:
1.  Sends the command with a "blocking" call.
2.  Waits for a short delay (2-5 seconds).
3.  Clears the internal cache and re-fetches the actual configuration from the Tesla API.
4.  Logs a success (✅) or failure (❌) message to provide a clear audit trail.

## 5. Observability & Troubleshooting

ABC is designed to be completely transparent:

### Troubleshooting Dashboard
A dedicated dashboard provides:
*   **Real-time State**: Current ABC state and the specific "Reason" for the current decision.
*   **Price Awareness**: Uses high-resolution sensors (`sensor.current_import_price_cents` and `sensor.current_export_price_cents`) to monitor market movements in real-time.
*   **Telemetry**: Real-time SOC vs. the dynamic Target SOC, current prices, and active flags.
*   **Live Configuration**: Every threshold, load value, and timer can be adjusted in real-time from the UI.

### Structured Logging
Logs are categorized with prefixes and emojis for easy scanning:
*   `ABC: [Data]` - Input variables (SOC, Prices).
*   `ABC: [Logic]` - Decisions, sunrise calculations, and transient buffers.
*   `ABC: [State Change]` - High-visibility notifications of mode transitions.
*   `ABC: [Hardware]` - Interactions with the Tesla API, including Amber override detections (🛡️, 🔌, ⚡).

## 6. Configuration Guide

| Setting | Purpose |
| :--- | :--- |
| **Emergency Min SOC** | The absolute floor for backup; system never discharges below this. |
| **High Price Min SOC** | The floor allowed during "Very High Price" events (default 40%). |
| **Overnight Load** | Average Watts used during sleep hours. |
| **Evening Load** | Baseline Watts used during active hours. |
| **Transient Duration** | How long to project current high-load spikes (default 60 min). |
| **Night Start** | When the "Active Phase" transitions to "Sleep Phase". |
| **Night End** | Fallback time for sunrise if Solcast is unavailable. |
| **Evening Peak** | Time window where selling down to target is prioritized. |
| **Export Min Earnings** | Stop exporting if earnings drop below this (default 0¢). |
| **Day Spike Threshold** | Price trigger for daytime selling. |
| **Very High Threshold** | Price trigger for "Risk Mode" selling. |
| **Import Stabilised** | Price below which the system exits BUFFER mode. |
| **Min Buffer Time** | Minimum minutes to stay in BUFFER after a spike ends. |
| **Min Mode Change** | Debounce timer (seconds) between Tesla API mode changes. |
| **Solcast Guardrail** | Prevents daytime selling if recharge is unlikely. |
