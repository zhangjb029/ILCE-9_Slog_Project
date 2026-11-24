"""R15 file layout recognition, exact object preservation, and activation gate.

Record/object validation is adapted from the released NAME HELP audit_snapshot.py.
No device communication is imported here.
"""
import struct
import zlib
from . import release_a9p as a9p
from .release_assets import sha, asset

CONFIG_NAMES = ('A9FL0.CFG','A9FL1.CFG','A9FW0.CFG','A9FW1.CFG')
CONFIG_PATHS = tuple('/setting/'+n for n in CONFIG_NAMES)
TABLE_IDS = (0x30004, 0x30005)
MODULE = '/usr/lib/a9fl.so'
BLOCKS = 80
BLOCK_SIZE = 4096


def require(condition, message):
    if not condition:
        raise ValueError(message)


def decode_record(name, raw):
    reason = f'{name}: invalid configuration record'
    require(len(raw) in (128,512,2048),reason+' length')
    n, gen, schema, mode = struct.unpack_from('<4I',raw,8)
    work = name.startswith('A9FW')
    tag = b'A9FLW001' if work else b'A9FLP001'
    count = {1:1,2:2,3:3,4:3,5:20,6:23,7:27,8:43,9:43}.get(schema,0)
    require(count and mode<=count and gen and n==len(raw) and
            n==(2048 if schema>=8 else 512 if schema>=5 else 128) and
            (not work or schema>=4) and
            (raw[:8]==tag or (schema==4 and raw[:8]==b'A7'+tag[2:])) and
            raw[56:88]==a9p.SHA and raw[88:112]==a9p.BUILD and
            int.from_bytes(raw[-4:],'little')==zlib.crc32(raw[:-4]),reason+' header/CRC')
    if schema>=4:
        begin = 24 if schema==4 else 128
        width = 16 if schema>=6 else 15
        bits = count*width*5
        end = begin+(bits+7)//8
        packed = int.from_bytes(raw[begin:end],'little')
        require(packed>>bits==0,reason+' reserved bits')
        if schema>=5:
            require(not any(raw[24:56]) and not any(raw[120 if schema>=8 else 116:128]) and
                    not any(raw[end+(16*33 if schema>=8 else 0):-4]),reason+' reserved bytes')
        else:
            require(not any(raw[end:56]) and not any(raw[116:124]),reason+' reserved bytes')
        flat = [((packed>>(5*i))&31) for i in range(count*width)]
        banks = [[v-32 if v&16 else v for v in flat[b*width:(b+1)*width]] for b in range(count)]
    elif schema==3:
        require(not any(raw[48:56]) and not any(raw[116:124]),reason+' reserved bytes')
        banks = [struct.unpack_from('<8b',raw,24+8*b) for b in range(3)]
    else:
        require(schema==2 or not any(raw[116:124]),reason+' reserved bytes')
        banks = [struct.unpack_from('<8i',raw,24)]
        if schema==2:
            banks.append(struct.unpack_from('<8b',raw,116))
    require(all((0 if schema<6 and f==9 else a9p.MIN[f])<=v<=a9p.MAX[f]
                for bank in banks for f,v in enumerate(bank)),reason+' field range')
    refs = {}
    if schema>=8:
        for i in range(16):
            at = 558+i*33
            block, digest = raw[at],raw[at+1:at+33]
            require(block<=BLOCKS,reason+' object index')
            if block:
                refs[str(i+1)] = (block,digest.hex())
            else:
                require(not any(digest) and banks[27+i]==list(a9p.DEFAULT),reason+' empty object reference')
        require(mode<=27 or str(mode-27) in refs,reason+' active object absent')
    crc = list(struct.unpack_from('<II' if schema>=8 else '<I',raw,112))
    return dict(schema=schema,generation=gen,mode=mode,candidate_crc32=crc,refs=refs)


def audit_state(module, configs, tables, profile='R15-SD', layout=None):
    require(layout is not None, 'Explicit recognized layout required')
    begin = layout['object_offset']
    if profile in ('R14-SD','R15-SD','R15-ORIGINAL'):
        require(layout['object_blocks']==BLOCKS and layout['object_block_length']==BLOCK_SIZE and
                len(module)==begin+BLOCKS*BLOCK_SIZE and
                sha(module[:begin])==layout['immutable_prefix_sha256'],'a9fl.so fixed prefix/size differs')
    else:
        require(profile in ('R12','R13'),'unknown partition profile')
        if profile=='R12':
            require(sha(module)==R12_MODULE_SHA,'R12 a9fl.so differs')
    require(len(configs)==4 and len(tables)==2 and all(len(raw)==1280 for raw in tables),'four configuration records and two live tables required')
    records, found = {}, {}
    for name, raw in zip(CONFIG_NAMES,configs,strict=True):
        if raw is None:
            records[name]=None
            continue
        row = decode_record(name,raw)
        max_schema = {'R12':6,'R13':7,'R14-SD':8,'R15-SD':9,'R15-ORIGINAL':9}[profile]
        require(row['schema']<=max_schema,f"{name}: {profile} cannot use schema {row['schema']}")
        objects = {}
        for slot,(number,digest) in row.pop('refs').items():
            if number not in found:
                at=begin+(number-1)*BLOCK_SIZE
                block=module[at:at+BLOCK_SIZE]
                require(not any(block[2756:]),f'{name} slot {slot}: object {number} has nonzero padding')
                try:
                    found[number]=a9p.inspect(block[:2756])
                except ValueError as exc:
                    raise ValueError(f'{name} slot {slot}: object {number} invalid: {exc}') from exc
            obj=found[number]
            require(obj['sha256_payload']==digest,f'{name} slot {slot}: object {number} SHA-256 mismatch')
            objects[slot]=dict(block=number,name=obj['name'],sha256_payload=digest)
        records[name]=dict(row,objects=objects)
    for i in (0,2):
        left,right=(records[name] for name in CONFIG_NAMES[i:i+2])
        if left and right:
            delta=abs(left['generation']-right['generation'])
            require(delta==1 if i==2 else delta!=0 or configs[i]==configs[i+1],
                    'configuration record generations conflict')
    current_crc=[zlib.crc32(data) for data in tables]
    match=[name for name,row in records.items() if row and row['schema']>=8 and row['candidate_crc32']==current_crc]
    first_only=[name for name,row in records.items() if row and row['schema']<8 and row['candidate_crc32']==current_crc[:1]]
    factory=tuple(tables)==a9p.stock()
    return dict(records=records,live_pair=dict(sha256=[sha(x) for x in tables],crc32=current_crc,
               factory_pair_exact=factory,matching_records=match,legacy_table0_crc_matches=first_only,
               status='record-pair-match' if match else 'factory-pair' if factory else 'legacy-table0-only' if first_only else 'no-record-pair-match'),
               unreferenced_nonzero_blocks=[n for n in range(1,BLOCKS+1) if profile in ('R14-SD','R15-SD','R15-ORIGINAL') and n not in found and
                   any(module[begin+(n-1)*BLOCK_SIZE:begin+n*BLOCK_SIZE])])


def recognize(module, package):
    for layout in package['sources']:
        begin = layout['object_offset']
        if len(module) == begin + BLOCKS*BLOCK_SIZE and sha(module[:begin]) == layout['immutable_prefix_sha256']:
            return layout
    raise ValueError('Unsupported a9fl.so code identity or object layout')


def prepare(module, configs, tables, package):
    source = recognize(module, package)
    state = audit_state(module, configs, tables, source['profile'], source)
    require(state['live_pair']['status'] != 'no-record-pair-match', 'Live tables do not match configuration or factory pair')
    target = next(x for x in package['sources'] if x['profile'] == package['target_profile'])
    payload = asset('r15/a9fl.so')
    begin = target['object_offset']
    require(sha(payload[:begin]) == target['immutable_prefix_sha256'], 'Target prefix changed')
    objects = module[source['object_offset']:]
    result = payload[:begin] + objects
    final = audit_state(result, configs, tables, target['profile'], target)
    return result, dict(source_profile=source['profile'], source_sha256=sha(module),
        target_sha256=sha(result), target_prefix_sha256=target['immutable_prefix_sha256'],
        object_blocks_preserved=80, object_area_sha256=sha(objects),
        config_sha256=[sha(x) if x is not None else None for x in configs],
        table_sha256=[sha(x) for x in tables], source_state=state, target_state=final,
        configuration_migration='R14 schema8 bytes retained; target first-load schema9 migration requires activation verification',
        replacement_enabled=False, activation_verified=False)


def require_replacement_protocol():
    # Deliberately no caller-provided override. /proc/maps alone cannot prove
    # that snapshot restore will not revive the old writer. A future implementation
    # must close this protocol using reviewed device-specific evidence.
    raise RuntimeError('R15 replacement blocked: stable owner/snapshot protocol is not proven; prepare/readback remain available')


def verify_activation(module, configs, tables, package, prepared_report,
                      runtime_module=None, loaded_state=None):
    """Keep on-disk bytes, executing code, and loaded user state separate.

    runtime_module must come from an independently authenticated runtime collector,
    and loaded_state from the new owner's diagnostics. No such collector is enabled
    in this release; local files or a /proc/maps path cannot stand in for it.
    """
    layout = recognize(module, package)
    state = audit_state(module, configs, tables, layout['profile'], layout)
    files_match = sha(module) == prepared_report['target_sha256']
    code_match = runtime_module is not None and sha(runtime_module[:layout['object_offset']]) == prepared_report['target_prefix_sha256']
    objects_match = loaded_state is not None and loaded_state.get('object_area_sha256') == prepared_report['object_area_sha256']
    # schema8 -> schema9 may legitimately change config bytes. Validate records
    # and require explicit owner load evidence instead of accepting equal files.
    migrated = all(row is None or row['schema']==9 for row in state['records'].values())
    loaded_configs = loaded_state is not None and loaded_state.get('config_sha256') == [sha(x) if x is not None else None for x in configs]
    loaded_tables = loaded_state is not None and loaded_state.get('table_sha256') == [sha(x) for x in tables]
    activated = bool(files_match and code_match and objects_match and migrated and loaded_configs and loaded_tables)
    return dict(state='ACTIVATION_VERIFIED' if activated else 'ACTIVATION_UNPROVEN',
        file_transfer_verified=files_match, runtime_code_verified=bool(code_match),
        objects_loaded_verified=bool(objects_match), configuration_migration_verified=migrated and bool(loaded_configs),
        live_tables_loaded_verified=bool(loaded_tables), activation_verified=activated,
        runtime_collector_enabled=False, live_state=state)
