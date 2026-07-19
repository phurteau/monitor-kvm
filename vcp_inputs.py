"""
Reference table of DDC/CI VCP 0x60 "Input Source" values.

IMPORTANT: These values are NOT universally standardized. The MCCS spec
defines a baseline (0x01-0x12), but many vendors (especially LG and Samsung)
use out-of-spec values. This table is only a *starting suggestion* list for
the Learn wizard -- the app always confirms the real value against live
hardware before saving it into a profile.

VCP feature code for Input Source = 0x60.
"""

INPUT_SOURCE_VCP = 0x60

# label -> value.  Ordered roughly by how common they are.
# The GUI shows these as suggestions; the Learn wizard proves which one works.
COMMON_INPUTS = [
    # --- MCCS standard baseline (Dell, HP, ASUS, AOC, Acer, Philips, many others) ---
    ("DisplayPort 1 (standard 0x0F)", 0x0F),
    ("HDMI 1 (standard 0x11)",        0x11),
    ("HDMI 2 (standard 0x12)",        0x12),
    ("DisplayPort 2 (standard 0x10)", 0x10),
    ("DVI 1 (standard 0x03)",         0x03),
    ("DVI 2 (standard 0x04)",         0x04),
    ("VGA / Analog 1 (standard 0x01)", 0x01),
    ("VGA / Analog 2 (standard 0x02)", 0x02),

    # --- USB-C variants seen in the wild ---
    ("USB-C (0x1B, some Dell)",  0x1B),
    ("USB-C (0x19)",             0x19),
    ("USB-C (0x20)",             0x20),
    ("USB-C (0xE0, some LG)",    0xE0),

    # --- LG out-of-spec values (very common) ---
    ("LG HDMI 1 (0x90)", 0x90),
    ("LG HDMI 2 (0x91)", 0x91),
    ("LG HDMI 3 (0x92)", 0x92),
    ("LG DisplayPort (0xD0)", 0xD0),
    ("LG DisplayPort 2 (0xD1)", 0xD1),

    # --- Samsung / misc out-of-spec values reported by users ---
    ("Samsung/HDMI (0x21)", 0x21),
    ("Samsung/DP (0x25)",   0x25),
    ("HDMI 3 (0x13)",       0x13),
    ("HDMI 4 (0x14)",       0x14),

    # --- legacy analog/video inputs ---
    ("Composite 1 (0x05)", 0x05),
    ("S-Video 1 (0x07)",   0x07),
    ("Component 1 (0x0C)", 0x0C),
]

# Friendly grouping for the profile UI: what the user thinks of as "the cable".
# Each maps to the ordered list of values to try first when learning.
CONNECTION_HINTS = {
    "DisplayPort": [0x0F, 0x10, 0xD0, 0xD1, 0x25],
    "HDMI":        [0x11, 0x12, 0x13, 0x14, 0x90, 0x91, 0x92, 0x21],
    "USB-C":       [0x1B, 0x19, 0x20, 0xE0],
    "DVI":         [0x03, 0x04],
    "VGA":         [0x01, 0x02],
}


# Friendly, clean input names shown FIRST in every input dropdown (no hex in the
# label, so the picker is easy to read). These are the MCCS-standard codes that
# work on most monitors. The full COMMON_INPUTS list is offered after these for
# non-standard panels.
FRIENDLY_INPUTS = [
    ("DisplayPort", 0x0F),
    ("DisplayPort 2", 0x10),
    ("HDMI 1", 0x11),
    ("HDMI 2", 0x12),
    ("USB-C", 0x1B),
    ("DVI", 0x03),
    ("VGA", 0x01),
]


def friendly_label_for_value(value: int) -> str:
    """Clean name for a value, e.g. 0x11 -> 'HDMI 1'. Falls back to hex."""
    for label, v in FRIENDLY_INPUTS:
        if v == value:
            return label
    for label, v in COMMON_INPUTS:
        if v == value:
            return label
    return f"Input 0x{value:02X}"


def input_menu():
    """Build the dropdown for choosing an input.

    Returns (display_list, {display_string: value}). Friendly names come first,
    then a separator, then the full advanced list - and the returned dict maps
    every display string straight to its integer value, so callers never parse
    hex out of a label (that was fragile and error-prone).
    """
    display = []
    mapping = {}
    seen_values = set()
    for label, val in FRIENDLY_INPUTS:
        display.append(label)
        mapping[label] = val
        seen_values.add(val)
    display.append("\u2500\u2500 more / non-standard \u2500\u2500")  # non-selectable-ish separator
    for label, val in COMMON_INPUTS:
        # keep the advanced entries with their descriptive labels
        display.append(label)
        mapping[label] = val
    return display, mapping


def label_for_value(value: int) -> str:
    """Best-effort human label for a raw VCP input value."""
    for label, v in COMMON_INPUTS:
        if v == value:
            return label
    return f"Input 0x{value:02X}"
