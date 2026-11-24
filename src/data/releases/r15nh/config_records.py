"""Read-only validation of the exact R14 engine configuration wire formats.

Schema5 is permanently 20x15 fields. Schema6 appends three banks and one
vignette field per bank, and permits signed halo. Schema7 is 27x16. Schema8 is 43x16 plus named object references. This module never migrates,
rewrites or down-converts a saved record.
"""
import struct
import zlib

from .guarded_config import PATHS, require

LOW = (-9, -9, -9, 0, -9, -3, 1, 0, 0, -9, -9, -9, -9, -9, -9, -9)
HIGH = (9, 9, 9, 9, 9, 3, 5, 9, 9, 9, 9, 9, 9, 9, 9, 9)


def parameters(raw, schema):
    require(schema in (1,4,5,6,7,8,9), 'Unsupported configuration schema')
    if schema>=8:
        require(len(raw)==2048 and not any(raw[24:56]) and not any(raw[120:128]) and
                not any(raw[1086:2044]), 'Configuration reserved bytes are nonzero or length differs')
        packed=int.from_bytes(raw[128:558],'little')
        return [[((packed>>((bank*16+field)*5))&31) -
                 (32 if (packed>>((bank*16+field)*5))&16 else 0)
                 for field in range(16)] for bank in range(43)]
    if schema in (5,6,7):
        require(len(raw)==512 and not any(raw[24:56]) and not any(raw[116:128]),
                'Configuration reserved bytes are nonzero or length differs')
        if schema==5:
            require(raw[315]&0xf0==0 and not any(raw[316:508]),
                    'Configuration reserved bytes/bits are nonzero')
            count,fields,end=20,15,316
        else:
            count,fields,end=(23,16,358) if schema==6 else (27,16,398)
            require(not any(raw[end:508]),'Configuration reserved bytes are nonzero')
        packed=int.from_bytes(raw[128:end],'little')
        return [[((packed >> ((bank*fields+field)*5)) & 31) -
                 (32 if (packed >> ((bank*fields+field)*5)) & 16 else 0)
                 for field in range(fields)] for bank in range(count)]
    require(len(raw)==128, 'Historical configuration length differs')
    require(not any(raw[116:124]), 'Configuration reserved bytes are nonzero')
    if schema == 1:
        return [struct.unpack_from('<8i', raw, 24)]
    require(raw[52] & 0xfe == 0 and not any(raw[53:56]),
            'Configuration packed reserved bits are nonzero')
    packed = int.from_bytes(raw[24:53], 'little')
    banks = []
    for bank in range(3):
        fields = []
        for field in range(15):
            value = (packed >> ((bank * 15 + field) * 5)) & 31
            fields.append(value - 32 if value & 16 else value)
        banks.append(fields)
    return banks


def validate(values, manifest, legacy_only=False, max_schema=9):
    require(set(values)==set(PATHS),'Configuration paths differ')
    expected_build = manifest['build'].encode().ljust(24, b'\0')
    pair = bytes.fromhex(manifest['pair_sha256'])
    records = {}
    for index, path in enumerate(PATHS):
        raw = values[path]
        if raw is None:
            records[path] = None
            continue
        require(len(raw) in (128, 512, 2048), 'Existing configuration is incomplete: ' + path)
        schema = struct.unpack_from('<I', raw, 16)[0]
        magic = b'A9FLP001' if index < 2 else b'A9FLW001'
        r9_magic = b'A7FLP001' if index < 2 else b'A7FLW001'
        # Only schema4 was written by the published R9 A9 engine.
        compatible_magic = raw[:8] == magic or (schema == 4 and len(raw) == 128 and raw[:8] == r9_magic)
        require(compatible_magic and struct.unpack_from('<I', raw, 8)[0] == len(raw)
                and raw[56:88] == pair and raw[88:112] == expected_build
                and struct.unpack_from('<I', raw, len(raw)-4)[0] == zlib.crc32(raw[:-4]),
                'Foreign or damaged configuration: ' + path)
        generation, schema, mode = struct.unpack_from('<III', raw, 12)
        allowed = (1,) if legacy_only else (1, 4, 5, 6, 7, 8, 9)
        require(generation > 0 and schema in allowed and schema<=max_schema and
                len(raw)==(2048 if schema>=8 else 512 if schema in (5,6,7) else 128),
                'Unsupported configuration schema/generation: ' + path)
        require(mode <= (1 if schema == 1 else 43 if schema >= 8 else 27 if schema == 7 else 23 if schema == 6 else 20 if schema == 5 else 3),
                'Unsupported configuration mode: ' + path)
        require(index < 2 or schema in (4, 5, 6, 7, 8, 9), 'Work record must be schemas4 through8')
        for bank in parameters(raw, schema):
            require(all((0 if schema<6 and field==9 else LOW[field]) <= value <= HIGH[field]
                        for field, value in enumerate(bank)),
                    'Configuration parameter out of range: ' + path)
        if schema>=8:
            banks=parameters(raw,8)
            for slot in range(16):
                at=558+33*slot
                block=raw[at]
                require(block<=80, 'Custom LUT reference is out of range')
                require(block or (not any(raw[at+1:at+33]) and banks[27+slot]==[0]*6+[1]+[0]*9),
                        'Empty custom LUT bank has a reference or nondefault controls')
            require(mode<=27 or raw[558+33*(mode-28)]!=0, 'Selected custom LUT slot is empty')
        records[path] = dict(generation=generation, schema=schema, mode=mode)
    for group in (PATHS[:2], PATHS[2:]):
        first, second = (records[path] for path in group)
        if first and second:
            if group == PATHS[2:]:
                require(abs(first['generation'] - second['generation']) == 1,
                        'Work-record generations conflict')
            elif first['generation'] == second['generation']:
                require(values[group[0]] == values[group[1]],
                        'Preference generations conflict')
    return records
