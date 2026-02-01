# custom_components/power_sync/advanced_battery_control_types.py
from enum import Enum

class ABCState(Enum):
    """States for the Advanced Battery Control state machine."""
    NORMAL = "NORMAL"
    SELLING = "SELLING"
    BUFFER = "BUFFER"
