"""Unit tests for minimal._pick_position (monitor-aware restore of the pill).

These reproduce the owner's actual staggered layout, where the virtual-desktop
bounding box is an L-shape with dead space no physical monitor covers, and
assert the pill only ever restores onto a real display.

Pure geometry: no Tk display and no real monitors are needed. Displays are
plain SimpleNamespace stubs exposing just .x/.y/.width/.height/.primary.
"""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from minimal import _pick_position  # noqa: E402


def disp(x, y, w, h, primary=False):
    return SimpleNamespace(x=x, y=y, width=w, height=h, primary=primary)


# Owner's real layout: primary 3840x2160 at the origin, plus a smaller display
# offset down-and-right so the virtual bounding box is 5568x3072 (an L-shape).
def staggered():
    return [
        disp(0, 0, 3840, 2160, primary=True),
        disp(3840, 2160, 1728, 912),
    ]


BAR_W = 300
BAR_H = 40


class PickPositionTests(unittest.TestCase):
    def test_fully_on_secondary_is_unchanged(self):
        pos = _pick_position(3900, 2200, BAR_W, BAR_H, staggered())
        self.assertEqual(pos, (3900, 2200))

    def test_hanging_off_edge_is_nudged_onto_that_display(self):
        # 20px past the primary's right edge (3840); should pull back to 3540
        # (3840 - 300) and stay on the primary, not jump to the secondary.
        pos = _pick_position(3560, 100, BAR_W, BAR_H, staggered())
        self.assertEqual(pos, (3540, 100))

    def test_bounding_box_dead_space_resets_to_primary_default(self):
        # (5000, 500) is inside the 5568x3072 bounding box (so the OLD clamp
        # accepted it) but lands on NO real display.
        pos = _pick_position(5000, 500, BAR_W, BAR_H, staggered())
        self.assertEqual(pos, ((3840 - BAR_W) // 2, 8))

    def test_wildly_out_of_range_resets_to_primary_default(self):
        pos = _pick_position(999999, -4000, BAR_W, BAR_H, staggered())
        self.assertEqual(pos, ((3840 - BAR_W) // 2, 8))

    def test_no_saved_position_is_primary_default_centered(self):
        pos = _pick_position(None, None, BAR_W, BAR_H, staggered())
        self.assertEqual(pos, ((3840 - BAR_W) // 2, 8))

    def test_primary_not_at_origin_uses_its_own_origin(self):
        displays = [disp(-1920, 0, 3840, 2160, primary=True)]
        pos = _pick_position(None, None, BAR_W, BAR_H, displays)
        self.assertEqual(pos, (-1920 + (3840 - BAR_W) // 2, 8))

    def test_empty_display_list_returns_none(self):
        self.assertIsNone(_pick_position(100, 100, BAR_W, BAR_H, []))


if __name__ == "__main__":
    unittest.main()
