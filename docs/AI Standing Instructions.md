# docs/AI_STANDING_INSTRUCTIONS.md

## Purpose

This file contains “standing instructions” for interacting with the JetBrains AI Assistant in this repository, especially when iterating on PowerSync features.  
Copy/paste the section **“Paste into a new chat”** at the start of any new conversation.

---

## Paste into a new chat

Standing instructions (apply to all future replies in this chat):

1) For **any new file code block**, the **first line inside the code block** must be a comment containing the file path (e.g. `# custom_components/power_sync/foo.py`).

2) For **edits to existing source files**, still use the required `<llm-snippet-file>...</llm-snippet-file>` wrapper **outside** the code block, and the **first line inside the code block** must also be a comment containing the file path.

3) Keep responses **concise and implementation-focused**:
    - Prefer concrete file lists, functions, and minimal scaffolding.
    - Avoid long explanations unless asked.
    - Clearly separate “what to change” vs “why”.

4) Never include real secrets (tokens/passwords/keys). Use placeholders like `<TOKEN>`.

Confirm you will follow these.

---

## Repository conventions (optional notes)

- Prefer adding new logic behind feature toggles/switches before wiring full configuration UI.
- When introducing new behaviour that may conflict with existing features, implement a single “is active?” gate function and reference it consistently.
- Keep user-facing naming consistent:
    - **TOU control** = standard tariff syncing mode
    - **Advanced battery control** = active controller mode that may switch operation modes automatically
