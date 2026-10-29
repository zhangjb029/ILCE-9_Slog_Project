"""The camera's own Fn table: slot properties, saved values, and what is known about each."""
from dataclasses import dataclass

from . import data

# PP feature-override property. Only these five offsets may be set to 0x02.
OVERRIDE = 0x00880000
OVERRIDE_OFFSETS = (0xa2, 0xa3, 0xa5, 0xa7, 0xab)

# Fn slot -> backup property. The order is not linear: Fn10-12 sit after Fn1.
FN_SLOTS = {
    1: 0x01070be8, 2: 0x01070bec, 3: 0x01070bed, 4: 0x01070bee,
    5: 0x01070bef, 6: 0x01070bf0, 7: 0x01070bf1, 8: 0x01070bf2,
    9: 0x01070bf3, 10: 0x01070be9, 11: 0x01070bea, 12: 0x01070beb,
}
SLOT_PIDS = tuple(FN_SLOTS.values())

# The Fn resolver rejects any saved value above 0x6E before it consults its table.
VALUE_LIMIT = 0x6e

VERIFIED = {0x3A, 0x36}
KNOWN_BAD = {0x64}

STATUS_VERIFIED = 'verified'
STATUS_UNTESTED = 'untested'
STATUS_KNOWN_BAD = 'known_bad'


@dataclass(frozen=True)
class FunctionItem:
    value: int
    symbol: str
    chinese: str
    status: str


def status_of(value: int) -> str:
    if value in KNOWN_BAD:
        return STATUS_KNOWN_BAD
    if value in VERIFIED:
        return STATUS_VERIFIED
    return STATUS_UNTESTED


def slot_label(number: int) -> str:
    return f'Fn{number}'


def load_functions() -> list[FunctionItem]:
    """Every saved value the camera's own Fn resolver accepts, in value order.

    Built from viewUnified4.so's switch table, so the list is exactly the set
    the camera can resolve. A byte routed through a capability branch maps to
    two nodes; keeping the first by value gives one row per saved value.
    """
    rows = data.resource_json('a9_fn_functions.json')['rows']
    names = {int(k, 16): v for k, v in data.resource_json('a9_fn_chinese_names.json').items()}
    items, seen = [], set()
    for row in rows:
        if not row['in_range']:
            continue
        value = int(row['value'], 16)
        if value in seen:
            continue
        seen.add(value)
        record = names.get(value, {})
        items.append(FunctionItem(
            value=value,
            symbol=row['name'],
            chinese=record.get('chinese') or row['name'],
            status=status_of(value),
        ))
    return sorted(items, key=lambda item: item.value)
