from __future__ import annotations

from enum import StrEnum


class ContainerType(StrEnum):
    GRID_BOX = "grid_box"
    BINDER = "binder"
    DRAWER = "drawer"
    BIN = "bin"


class SlotType(StrEnum):
    GRID_REGION = "grid_region"
    CARD = "card"
    SLOT = "slot"
    BULK = "bulk"


class PackagingType(StrEnum):
    CUT_TAPE = "cut_tape"
    LOOSE = "loose"
    TUBE = "tube"
    REEL = "reel"
    ANTI_STATIC_BAG = "anti_static_bag"
    BULLDOG_CLIPPED_BAG = "bulldog_clipped_bag"
    OTHER = "other"


class StockStatus(StrEnum):
    ACTIVE = "active"
    RESERVED = "reserved"
    CONSUMED = "consumed"


class CellSize(StrEnum):
    SMALL = "small"
    LARGE = "large"


class CellLength(StrEnum):
    SHORT = "short"
    LONG = "long"


class StorageClass(StrEnum):
    SMALL_SHORT_CELL = "small_short_cell"
    LARGE_CELL = "large_cell"
    LONG_CELL = "long_cell"
    BINDER_CARD = "binder_card"


class BuildStatus(StrEnum):
    PLANNED = "planned"
    PARTS_PULLED = "parts_pulled"
    BUILT = "built"
    DEBUG = "debug"
    DONE = "done"
