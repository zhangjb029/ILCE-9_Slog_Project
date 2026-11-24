"""Released R15 NAME HELP through the proven R12 FF01 full-partition path.

Only /dev/nflasha15 receives a 300 MiB write. Four configuration records and
two LUT properties are preserved on install, and restored as a paired snapshot
on explicit rollback. File replacement and runtime activation remain separate.
"""
import hashlib
import importlib.util
import json
import lzma
import re
import shutil
import struct
import sys
import types
import uuid
from functools import lru_cache
from pathlib import Path

from . import data, usbdev, menu_deploy
from .file_deploy import durable, identity_key

PARTITION = '/dev/nflasha15'
PARTITION_BYTES = 314572800
TARGET_SHA = '704d9401fb8f63823ffde6a8812eda38ae27d81d6432bf8332cdad95e46233da'
MANIFEST_SHA = '364c2e3167963574d5e3ec35fa0bb5b40a880427b0dd28cbe1079ac6083dbb74'
ACTIONS = frozenset('r15.'+x for x in ('check','backup','status','identify','patch','prepare','install','rollback'))
ROOT = data.data_root()/'releases'/'r15nh'


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _save(path, value):
    durable(path, (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode('utf-8'))


@lru_cache(maxsize=1)
def package():
    raw = (ROOT/'manifest.json').read_bytes()
    _require(_sha(raw)==MANIFEST_SHA, 'R15NH manifest checksum differs')
    manifest = json.loads(raw)
    _require(manifest['schema']=='a9-r15nh-r12p-release-v2' and
             manifest['partition']==PARTITION and manifest['partition_bytes']==PARTITION_BYTES and
             manifest['candidate_sha256']==TARGET_SHA, 'R15NH package binding differs')
    for name, row in manifest['files'].items():
        path = (ROOT/name).resolve()
        _require(path.is_relative_to(ROOT.resolve()), 'Release path escaped package')
        payload = path.read_bytes()
        _require(len(payload)==row['bytes'] and _sha(payload)==row['sha256'], 'R15NH asset changed: '+name)
    return manifest


@lru_cache(maxsize=1)
def runtime():
    """Load the released pure Python transaction without importing its USB CLI."""
    package()
    prefix = 'a9tool._r15nh_released'
    namespace = types.ModuleType(prefix)
    namespace.__path__ = [str(ROOT)]
    sys.modules[prefix] = namespace
    result = {}
    for name in ('guarded_config','snapshot_fs','config_records','lut_backup','readback_rules','partition_core'):
        spec = importlib.util.spec_from_file_location(prefix+'.'+name, ROOT/(name+'.py'))
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        result[name] = module
    return types.SimpleNamespace(**result)


def _write_verified(path,raw):
    path=Path(path)
    if path.exists():
        _require(path.read_bytes()==raw,'Existing local evidence differs; refusing to overwrite: '+path.name)
    else:
        durable(path,raw)


def _record_verified(path,value):
    _write_verified(path,(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))


def _patch_runs(row):
    blob=lzma.decompress((ROOT/row['patch']).read_bytes())
    _require(blob[:4]==b'R12P' and len(blob)>=8,'Invalid R12P patch header')
    count=struct.unpack_from('<I',blob,4)[0];pos=8;offset=0;runs=[];previous_end=0
    for _ in range(count):
        _require(pos+8<=len(blob),'Truncated patch run')
        delta,length=struct.unpack_from('<II',blob,pos);pos+=8;offset+=delta
        _require(length>0 and previous_end<=offset and offset+length<=PARTITION_BYTES and pos+length<=len(blob),'Invalid patch run bounds')
        runs.append((offset,blob[pos:pos+length]));pos+=length;previous_end=offset+length
    _require(pos==len(blob) and count==row['patch_statistics']['offset_runs'] and
             sum(len(data) for _,data in runs)==row['patch_statistics']['changed_bytes'],'Patch statistics differ')
    return runs


def _validate_external(arguments):
    canonical=(ROOT/'manifest.json').read_bytes()
    if arguments.get('manifest') is not None:
        value=arguments['manifest']
        _require(isinstance(value,str) and Path(value).is_absolute(), 'manifest must be an absolute path')
        _require(Path(value).read_bytes()==canonical,'External R15NH manifest differs from the built-in release')
    if arguments.get('package') is not None:
        value=arguments['package']
        _require(isinstance(value,str) and Path(value).is_absolute(),'package must be an absolute directory')
        folder=Path(value).resolve()
        _require((folder/'manifest.json').read_bytes()==canonical,'External R15NH package manifest differs')
        for name,row in package()['files'].items():
            path=(folder/name).resolve()
            _require(path.is_relative_to(folder),'External release path escaped directory')
            raw=path.read_bytes()
            _require(len(raw)==row['bytes'] and _sha(raw)==row['sha256'],'External R15NH package asset differs: '+name)


class PartitionGuard:
    """One exact FF01 block-device write; no /usr single-file write route."""
    def __init__(self, transport, allow_write=False):
        self.transport, self.allow_write, self.writes = transport, allow_write, 0

    def sendSenserPacket(self, function, packet, oData=None):
        if function==0x10 and packet==struct.pack('<HHB',0,0x1f,0):
            return self.transport.sendSenserPacket(function, packet)
        _require(function==0xff01 and isinstance(packet,bytes) and len(packet)>=4, 'Only bounded FF01 is allowed')
        cmd,n = struct.unpack_from('<hh',packet)
        _require(n>0 and n%4==0 and 4+n<=len(packet), 'Invalid FF01 name length')
        name = packet[4:4+n].rstrip(b'\0').decode('ascii')
        encoded=name.encode('ascii')
        _require(packet[4:4+n]==encoded+bytes(4-len(encoded)%4), 'Invalid FF01 path padding')
        body = packet[4+n:]
        if cmd==2:
            _require(name in (PARTITION,'/setting/updater/dat4','/setting/updater/COMP') and not body,
                     'Partition read path is not allowlisted')
        else:
            _require(cmd==1 and self.allow_write and oData is None and name==PARTITION and
                     len(body)==PARTITION_BYTES and self.writes==0, 'Only one complete 300 MiB partition write is allowed')
            self.writes += 1
        return self.transport.sendSenserPacket(function, packet, oData)


def make_guard(transport, allow_write=False):
    config = runtime().guarded_config
    class Guard(config.ConfigGuard):
        def sendSenserPacket(self, function, packet, oData=None):
            # The existing factory read primitive also reads one fixed preload
            # file, solely to prevent an R15 rollback under an active V8 owner.
            if function==0x40 and isinstance(packet,bytes) and len(packet)>=4:
                block,code=struct.unpack_from('<HH',packet)
                if block==0x1001 and code==0x4008 and packet[4:]==b'\1\0\0/../etc/ld.so.preload\0':
                    _require(self.initialized and oData is None, 'Preload read was not initialized')
                    return self.transport.sendSenserPacket(function,packet)
            return super().sendSenserPacket(function,packet,oData)
    # Exact CFG rollback must use the app's BoundedSenser send method too;
    # invoking the upstream base class would bypass deadline/unpadded framing.
    return Guard(transport, PartitionGuard(transport,allow_write).sendSenserPacket,
                 native_send=transport.sendSenserPacket)


def _read_preload(camera):
    status,raw = camera.dev.sendSenserPacket(0x40,struct.pack('<HH',0x1001,0x4008)+b'\1\0\0/../etc/ld.so.preload\0')
    _require(status==0 and isinstance(raw,bytes) and 4<=len(raw)<=16388, 'Invalid preload read response')
    code=struct.unpack_from('<I',raw)[0]
    if code==runtime().guarded_config.MISSING:
        _require(len(raw)==4, 'Missing preload returned data')
        return None
    _require(code==0, 'Preload read failed')
    return raw[4:]


def check_v8_inactive(camera):
    raw=_read_preload(camera)
    if raw is None:
        return
    text=raw.decode('ascii')
    _require(not any(ord(c)<32 and c not in '\r\n\t' for c in text), 'Invalid preload controls')
    tokens=[t for line in text.splitlines() for t in re.split(r'[\s:]+',line.split('#',1)[0]) if t]
    _require(not any('v71mt' in t.lower() or 'a9v8' in t.lower() for t in tokens),
             'V8 is active; roll back V8 before changing the R15 partition')


def _normalized_sha(raw, regions):
    h=hashlib.sha256(); pos=0
    for start,end in sorted(regions):
        _require(pos<=start<=end<=len(raw), 'Invalid source comparison region')
        h.update(memoryview(raw)[pos:start]); h.update(bytes(end-start)); pos=end
    h.update(memoryview(raw)[pos:])
    return h.hexdigest()


def classify(raw, configs, tables):
    """Authenticate all partition bytes, excluding only pinned lifecycle fields."""
    rt=runtime(); rt.partition_core.validate_partition(raw,package())
    fs=rt.snapshot_fs.Ext2.from_bytes(raw)
    paths=list(package()['sources'][0]['files'])
    actual={}
    for path in paths:
        try: value=fs.inode_data(fs.lookup(path.removeprefix('/usr/')))
        except FileNotFoundError: value=None
        actual[path]=value
    for row in package()['sources']:
        layout=row.get('object_layout')
        matched=True
        for path,want in row['files'].items():
            value=actual[path]
            if layout and path=='/usr/lib/a9fl.so':
                good=value is not None and len(value)==layout['object_offset']+80*4096 and _sha(value[:layout['object_offset']])==layout['immutable_prefix_sha256']
            else:
                good=(None if value is None else _sha(value))==want
            if not good: matched=False; break
        if not matched:
            continue
        _require(_normalized_sha(raw,row['normalization_regions'])==row['normalized_partition_sha256'],
                 'Source partition differs outside the released files and named ext2 metadata')
        max_schema=row['config_schema'] or 9
        rt.config_records.validate(configs,package(),max_schema=max_schema)
        if layout:
            from . import r15_files
            state=r15_files.audit_state(actual['/usr/lib/a9fl.so'],[configs[p] for p in rt.guarded_config.PATHS],
                                        [tables[p] for p in rt.guarded_config.LUT_IDS],layout['profile'],layout)
            _require(state['live_pair']['status']!='no-record-pair-match','Live LUT pair conflicts with saved records')
        else:
            state={'legacy_configuration_preserved':True}
        return dict(label=row['label'],r15nh_current=row['label']=='R15 NAME HELP',
                    canonical_sha256=row['canonical_sha256'],object_layout=layout,state=state)
    raise ValueError('Unknown or mixed partition release; no write sent')


def prepare_image(source_raw, configs, tables, destination=None):
    report=classify(source_raw,configs,tables)
    row=next(x for x in package()['sources'] if x['label']==report['label'])
    _require('patch' in row,'R15 NAME HELP is already current; no patch or reflash is needed')
    canonical=bytearray(source_raw)
    for region in row['canonical_metadata']:
        start,end=region['start'],region['end'];value=bytes.fromhex(region['hex'])
        _require(len(value)==end-start,'Canonical metadata size differs')
        canonical[start:end]=value
    _require(_sha(canonical)==row['canonical_sha256'],'Normalized source is not the formal pinned source')
    payload=menu_deploy._apply(canonical,_patch_runs(row))
    _require(len(payload)==PARTITION_BYTES and _sha(payload)==TARGET_SHA,'Locally patched full partition SHA256 differs')
    classify(payload,configs,tables)
    report.update(target_sha256=_sha(payload),source_sha256=_sha(source_raw),patch=row['patch'],patch_statistics=row['patch_statistics'],
                  partition=PARTITION,partition_bytes=PARTITION_BYTES,transport='FF01_FULL_PARTITION',
                  candidate_origin='local R12P patch applied to authenticated camera backup',
                  configuration_migration='Original records retained; released engine migrates on load')
    if destination is not None:
        _record_verified(Path(destination)/'prepared.json',report)
    return payload,report


def load_rollback(source):
    source=Path(source).resolve();rt=runtime()
    record=json.loads((source/'capture.json').read_text('utf-8'))
    _require(record.get('schema')=='a9-r15nh-session-v1','Unknown R15NH rollback session')
    identity=identity_key(record['identity'])
    configs=rt.guarded_config.load_snapshot(source/'config_before',identity)
    tables=rt.lut_backup.load_snapshot(source/'luts_before',identity)
    part=source/'partition'
    # Captures/preparations are also valid rollback sources, before any install.
    payload=(part/'preimage.bin').read_bytes()
    _require(len(payload)==PARTITION_BYTES and _sha(payload)==record['preimage_sha256'], 'Rollback partition backup checksum differs')
    classify(payload,configs,tables)
    return payload,configs,tables,identity


def _material_identity(raw,configs,tables,identity):
    return dict(identity=identity,source_sha256=_sha(raw),
                config_sha256={p:None if v is None else _sha(v) for p,v in configs.items()},
                table_sha256={str(p):_sha(v) for p,v in tables.items()})


def _identified(source,material):
    raw,configs,tables,identity=material
    report=classify(raw,configs,tables)
    return dict(schema='a9-r15nh-identified-v2',source_label=report['label'],
                r15nh_current=report['r15nh_current'],patch_supported=not report['r15nh_current'],
                **_material_identity(raw,configs,tables,identity))


def _load_identified(source,material):
    path=Path(source)/'identified.json'
    _require(path.is_file(),'Identify the saved backup before local patching or installation')
    expected=_identified(source,material)
    _require(json.loads(path.read_text('utf-8'))==expected,'Identified backup evidence differs')
    return expected


def _load_prepared(source):
    source=Path(source).resolve();material=load_rollback(source)
    identified=_load_identified(source,material)
    _require(identified['patch_supported'],'R15 NAME HELP is already current; no reflash is needed')
    path=source/'prepared.json'
    _require(path.is_file() and (source/'prepared-partition.bin').is_file(),
             'Patch the identified backup locally before installation')
    report=json.loads(path.read_text('utf-8'));payload=(source/'prepared-partition.bin').read_bytes()
    _require(len(payload)==PARTITION_BYTES and _sha(payload)==TARGET_SHA and report.get('target_sha256')==TARGET_SHA,
             'Prepared candidate checksum differs')
    for key,value in _material_identity(*material).items():
        _require(report.get(key)==value,'Prepared candidate does not belong to this paired backup: '+key)
    row=next(x for x in package()['sources'] if x['label']==identified['source_label'])
    _require(report.get('patch')==row['patch'] and report.get('patch_statistics')==row['patch_statistics'],
             'Prepared delta identity differs')
    classify(payload,material[1],material[2])
    return payload,material,report


def inspect_session(source):
    """Pure local validation used by native UI button gating; never opens USB."""
    folder=Path(source).resolve()
    result=dict(backup_valid=False,identified=False,patched=False,session=str(folder),source_label=None,reason='')
    try:
        material=load_rollback(folder);result['backup_valid']=True
        result['source_label']=classify(material[0],material[1],material[2])['label']
        _load_identified(folder,material);result['identified']=True
        _load_prepared(folder);result['patched']=True
    except (OSError,ValueError,KeyError,TypeError,AssertionError,struct.error) as error:
        result['reason']=str(error)
    return result


def _source(arguments):
    value=arguments.get('source') or arguments.get('saved_session')
    _require(isinstance(value,str) and Path(value).is_absolute(),'source must be an absolute saved backup session path')
    return Path(value).resolve()


def _capture(camera, identity, folder, allow_unknown=False):
    rt=runtime();config=rt.guarded_config.Configuration(camera)
    config.capture(folder/'config_before',identity)
    configs=rt.guarded_config.load_snapshot(folder/'config_before',identity)
    tab=rt.lut_backup.Tables(camera);tab.capture(folder/'luts_before',identity)
    tables=rt.lut_backup.load_snapshot(folder/'luts_before',identity)
    part=folder/'partition';part.mkdir()
    snapshot=rt.partition_core.read_to_file(camera,part/'preimage.bin',PARTITION)
    _require(snapshot['bytes']==PARTITION_BYTES,'Incomplete source partition; partial bytes retained')
    config.unchanged(configs);tab.unchanged(tables)
    raw=(part/'preimage.bin').read_bytes()
    try:
        report=classify(raw,configs,tables)
    except (ValueError, AssertionError, FileNotFoundError, struct.error) as error:
        if not allow_unknown:
            raise
        # A previous single write may have been interrupted. Exact, same-body
        # rollback material is authenticated separately; do not require the
        # damaged current image to be a complete released build.
        report=dict(label=None,r15nh_current=False,unknown=True,reason=str(error))
    _save(folder/'capture.json',dict(schema='a9-r15nh-session-v1',identity=identity,
          preimage_sha256=snapshot['sha256'],source=report,automatic_retry=False))
    return config,configs,tab,tables,raw,report


def _write_once(camera, identity, folder, payload, config, configs, tab, tables):
    rt=runtime();partition=folder/'partition';target=_sha(payload)
    def unchanged():
        config.unchanged(configs);tab.unchanged(tables);check_v8_inactive(camera)
    unchanged();camera.dev.before_partition_write=unchanged
    # Re-read the full live preimage immediately before mutation. Besides the
    # bounded configuration rechecks this catches an intervening partition edit.
    prior=rt.partition_core.read_to_file(camera,partition/'prewrite.bin',PARTITION)
    original=(partition/'preimage.bin').read_bytes()
    _require(prior['bytes']==PARTITION_BYTES,'Incomplete pre-write partition read; no write sent')
    if prior['sha256']!=_sha(original):
        rt.readback_rules.compare_complete(original,(partition/'prewrite.bin').read_bytes())
    unchanged()
    _save(partition/'intent.json',dict(partition=PARTITION,preimage_sha256=_sha(original),target_sha256=target,identity=identity,automatic_retry=False))
    if prior['sha256']==target:
        return dict(write_attempted=False,already_at_target=True,match_kind='EXACT')
    durable(partition/'target.bin',payload)
    _save(partition/'write_attempt.json',dict(target_sha256=target,automatic_retry=False))
    camera.writeFile(PARTITION,payload)
    back=rt.partition_core.read_to_file(camera,partition/'readback.bin',PARTITION)
    _require(back['bytes']==PARTITION_BYTES,'Incomplete full-partition readback; no retry sent')
    details=rt.readback_rules.compare_complete(payload,(partition/'readback.bin').read_bytes())
    config.unchanged(configs);tab.unchanged(tables)
    _save(partition/'result.json',dict(pass_=True,target_sha256=target,write_attempted=True,**back,**details))
    return dict(write_attempted=True,**details)


def execute(action, arguments, progress=None):
    _require(action in ACTIONS and isinstance(arguments,dict),'Unsupported R15NH action')
    manifest=package();_validate_external(arguments);say=progress or (lambda message:None)
    if action=='r15.check':
        return dict(state='RELEASE_ASSETS_VERIFIED',installation_enabled=True,initial_install_enabled=True,
                    supported_sources=[x['label']for x in manifest['sources']],transport='FF01_FULL_PARTITION',
                    partition=PARTITION,partition_bytes=PARTITION_BYTES,target_sha256=TARGET_SHA,
                    hardware_verified=False,r15nh_current=False,workflow='backup -> identify -> patch -> install',
                    contains_full_image=False,patch_sources=[x['label'] for x in manifest['sources'] if 'patch' in x])
    if action in ('r15.identify','r15.patch','r15.prepare'):
        source=_source(arguments);material=load_rollback(source)
        if action=='r15.identify':
            report=_identified(source,material)
            _record_verified(source/'identified.json',report)
            return dict(report,state='IDENTIFIED_BACKUP',session=str(source),rollback_available=True)
        _load_identified(source,material)
        payload,report=prepare_image(material[0],material[1],material[2])
        report.update(schema='a9-r15nh-prepared-v2',**_material_identity(*material))
        _require(shutil.disk_usage(source).free>=PARTITION_BYTES or (source/'prepared-partition.bin').exists(),
                 'Not enough disk space to save the locally patched candidate')
        _write_verified(source/'prepared-partition.bin',payload)
        _record_verified(source/'prepared.json',report)
        return dict(report,state='PREPARED_FULL_PARTITION',session=str(source),prepared_session=str(source),
                    rollback_available=True,r15nh_current=False)
    # Install is deliberately impossible without authenticated local identify
    # and patch receipts, checked before native USB discovery/connection.
    prepared=_load_prepared(_source(arguments)) if action=='r15.install' else None
    value=arguments.get('session_root')
    _require(isinstance(value,str) and Path(value).is_absolute(),'session_root must be absolute')
    root=Path(value);root.mkdir(parents=True,exist_ok=True)
    _require(shutil.disk_usage(root).free>=3*1024**3,
             'At least 3 GiB of free session disk space is required before connecting')
    restore=None;source=None
    if action=='r15.rollback':
        source=_source(arguments);restore=load_rollback(source)
    elif prepared:
        source=_source(arguments)
    payload=prepared[0] if prepared else None
    folder=root/(action.replace('.','-')+'-'+uuid.uuid4().hex);folder.mkdir()
    # Use the released 1.8.2 native connection and its existing same-port,
    # same-body, TTL-bound identity receipt when resuming service mode.
    handle=usbdev.connect(receipt=usbdev.load_current_receipt(),
                          guard_factory=lambda transport:make_guard(transport,action in ('r15.install','r15.rollback')),
                          response_timeout=900,progress=say)
    capture_complete=False
    try:
        identity=identity_key(handle.identity)
        if arguments.get('expected_identity') is not None:
            _require(identity==identity_key(arguments['expected_identity']),'Camera differs from installation plan identity')
        if restore:
            _require(identity==restore[3],'Rollback camera identity differs')
        if prepared:
            _require(identity==prepared[1][3],'Prepared backup camera identity differs')
        say('Reading complete 300 MiB partition, four records and two LUT properties')
        config,configs,tab,tables,raw,report=_capture(handle.camera,identity,folder,
            allow_unknown=restore is not None or action=='r15.status')
        capture_complete=True
        if action in ('r15.install','r15.rollback'):
            check_v8_inactive(handle.camera)
        source_validated = not report.get('unknown', False)
        source_state = ('unknown' if not source_validated else 'current' if report['r15nh_current']
                        else 'stock' if report['label']=='stock' else 'legacy')
        observation = dict(state=source_state, label=report['label'], state_validated=source_validated,
                           reason=report.get('reason',''), verification_scope='complete_partition_and_records')
        result=dict(state='READ_ONLY_COMPLETE',identity=identity,session=str(folder.resolve()),r15nh_current=report['r15nh_current'],
                    source_label=report['label'],r15=observation,activation_verified=False,
                    transport='FF01_FULL_PARTITION',rollback_available=source_validated)
        if prepared:
            baseline,old_configs,old_tables,_=prepared[1]
            runtime().readback_rules.compare_complete(baseline,raw)
            _require(configs==old_configs and tables==old_tables,'Saved backup configuration/LUT state is stale; create a fresh backup')
            result.update(prepared_target_sha256=prepared[2]['target_sha256'],prepared_session=str(source))
        if action in ('r15.install','r15.rollback'):
            if restore:payload=restore[0]
            say('Writing FF01 /dev/nflasha15 once, then reading all 300 MiB back')
            details=_write_once(handle.camera,identity,folder,payload,config,configs,tab,tables)
            if restore:
                config.restore(restore[1],folder/'config_restore');tab.restore(restore[2],folder/'lut_restore')
                final=classify(payload,restore[1],restore[2]);current=final['r15nh_current']
            else:current=True
            result.update(state='FULL_PARTITION_READBACK_VERIFIED',requires_cold_restart=True,r15nh_current=current,**details)
        _save(folder/'result.json',result)
        return result
    except BaseException as error:
        error.session=str(source) if restore or prepared else str(folder.resolve()) if capture_complete else None
        error.rollback_available=bool(restore or capture_complete)
        error.failure_session=str(folder.resolve())
        try:
            _save(folder/'failure.json',dict(error=type(error).__name__+': '+str(error),automatic_retry=False,
                  rollback_source=error.session,
                  instruction='Preserve this complete or partial session; no automatic retry or rollback'))
        except (OSError,ValueError) as logging_error:
            error.add_note('Could not save failure receipt: '+str(logging_error))
        raise
    finally:
        try:
            handle.close()
        except Exception:
            pass
