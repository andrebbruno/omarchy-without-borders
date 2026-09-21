"""Neighbour resolution from the MWB matrix (one row / two rows / wrap-around).

Mirrors MachineStuff.MoveLeft/Right/Up/Down from PowerToys. Run: python -m pytest tests
"""
from owb.daemon import Daemon


class _D(Daemon):
    """Daemon.neighbours() without a real daemon: fake matrix + connected set."""
    def __init__(self, matrix, me, connected, two_rows=False, circle=False):  # noqa: D107
        self.matrix = list(matrix) + [""] * (4 - len(matrix))
        self.machine_name = me
        self._connected = {c.upper() for c in connected}
        self.matrix_two_rows = two_rows
        self.matrix_circle = circle

    def peer_by_name(self, name):
        return object() if name.upper() in self._connected else None


ROW = ["A", "B", "C", "D"]


def test_one_row_basic():
    assert _D(ROW, "B", ROW).neighbours() == {"left": "A", "right": "C"}
    assert _D(ROW, "A", ROW).neighbours() == {"right": "B"}
    assert _D(ROW, "D", ROW).neighbours() == {"left": "C"}


def test_one_row_skips_disconnected():
    # MWB LiveMachineMatrix: disconnected slots are transparent in one-row mode
    assert _D(ROW, "B", ["A", "D"]).neighbours() == {"left": "A", "right": "D"}
    assert _D(ROW, "B", []).neighbours() == {}


def test_one_row_circle():
    assert _D(ROW, "A", ROW, circle=True).neighbours() == {"left": "D", "right": "B"}
    assert _D(ROW, "D", ROW, circle=True).neighbours() == {"left": "C", "right": "A"}
    # wrap also skips disconnected machines
    assert _D(ROW, "D", ["B", "C"], circle=True).neighbours() == {"left": "C", "right": "B"}


def test_one_row_empty_slots_and_case():
    assert _D(["A", "", "b", ""], "B", ["a"]).neighbours() == {"left": "A"}
    assert _D(ROW, "X", ROW).neighbours() == {}


def test_two_rows_grid():
    # [[A, B], [C, D]]
    assert _D(ROW, "A", ROW, two_rows=True).neighbours() == {"right": "B", "bottom": "C"}
    assert _D(ROW, "B", ROW, two_rows=True).neighbours() == {"left": "A", "bottom": "D"}
    assert _D(ROW, "C", ROW, two_rows=True).neighbours() == {"right": "D", "top": "A"}
    assert _D(ROW, "D", ROW, two_rows=True).neighbours() == {"left": "C", "top": "B"}


def test_two_rows_no_skipping_and_holes():
    # two-row mode does not skip disconnected machines (edge exists; activation will fail-safe)
    assert _D(ROW, "A", [], two_rows=True).neighbours() == {"right": "B", "bottom": "C"}
    assert _D(["A", "B", "", "D"], "B", ROW, two_rows=True).neighbours() == {"left": "A", "bottom": "D"}
    assert _D(["A", "B", "", "D"], "D", ROW, two_rows=True).neighbours() == {"top": "B"}


def test_two_rows_circle():
    assert _D(ROW, "A", ROW, two_rows=True, circle=True).neighbours() == \
        {"right": "B", "left": "B", "bottom": "C", "top": "C"}
    assert _D(ROW, "D", ROW, two_rows=True, circle=True).neighbours() == \
        {"left": "C", "right": "C", "top": "B", "bottom": "B"}
