"""A9 6.00 file installer: direct USB FileControl, no camera terminal.

Only explicit install/backup/status/rollback commands import USB. Digest
calculations and full-byte comparisons run on the PC. No partition writer,
arbitrary command, helper execution or automatic write retry exists.
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import posixpath
import re
import secrets
import struct
import sys
import tarfile
import tempfile
import time

NAMES=('a9-autoexec-v71mt.so', 'a9-v71mt.sh', 'a9-film-boot-v71mt.tar')
TARGETS=('/etc/a9-autoexec-v71mt.so', '/tmp/a9-v71mt.sh', '/tmp/a9-film-boot-v71mt.tar')
HOOK=TARGETS[0]
PRELOAD='/etc/ld.so.preload'
PRELOAD_BACKUP='/etc/a9-preload-v71mt.bak'
PATHS=TARGETS+(PRELOAD_BACKUP,PRELOAD)
MAX_FILE=8*1024*1024
MISSING=0x10000006
SCHEMA='a9-filecontrol-session-v71mt'
BUNDLE_NAMES=('prepare.sh','runtime-start.sh','a9-extra-menu.so','a9-extra-menu-guard.elf',
              'a9-check-persist.req','a9-install-persist.req','a9-remove-persist.req','a9-wps-boot.elf')

def require(value,message):
    if not value:raise ValueError(message)

def sha(data):return hashlib.sha256(data).hexdigest()

def save(path,data):
    with Path(path).open('xb') as output:
        output.write(data);output.flush();os.fsync(output.fileno())

def save_json(path,value):save(path,(json.dumps(value,indent=2,ensure_ascii=False)+'\n').encode('utf-8'))

def check_identity(identity):
    require(identity.get('model')=='ILCE-9' and identity.get('firmware')=='6.00','Only ILCE-9 firmware 6.00 is supported')
    require(re.fullmatch('[0-9a-f]{64}',identity.get('serial_sha256','')) is not None,'Missing camera identity')

def merge_preload(before):
    before=before or b''
    require(len(before)<=16384 and b'\0' not in before,'Invalid preload length or NUL')
    text=before.decode('ascii')
    require(all(c in '\r\n\t' or 32<=ord(c)<127 for c in text),'Invalid preload control character')
    def canonical(token):
        if not token.startswith('/'):return token
        token=posixpath.normpath('/'+token.lstrip('/')).casefold()
        return '/etc'+token[4:] if token.startswith('/tmp/') else token
    tokens=[canonical(word) for line in text.splitlines()
            for word in re.split(r'[\s:]+',line.split('#',1)[0]) if word]
    legacy='/etc/a9-autoexec-v71.so'
    if legacy in tokens:
        require(tokens.count(legacy)==1 and canonical(HOOK) not in tokens,
                'Mixed or duplicate Extra Menu preload entries; no upgrade performed')
        count=0
        def replace_line(line):
            nonlocal count
            code,mark,comment=line.partition('#')
            def word(match):
                nonlocal count
                if match.group(0)==legacy:
                    count+=1
                    return HOOK
                return match.group(0)
            return re.sub(r'[^:\s]+',word,code)+mark+comment
        rewritten=''.join(replace_line(line) for line in text.splitlines(keepends=True))
        require(count==1,'Only the exact V7 hook path can be upgraded')
        before=rewritten.encode('ascii')
        tokens=[canonical(word) for line in rewritten.splitlines()
                for word in re.split(r'[\s:]+',line.split('#',1)[0]) if word]
    old={'/etc/a9-autoexec-v7.so','/etc/a9boot/a9boot.so','/etc/a9boot.so','/etc/a6400-autoexec.so','/etc/a9b4.so','/etc/a9-autoexec.so','/etc/a9-autoexec-v51.so','/etc/a9-autoexec-v52.so','/etc/a9-autoexec-v53.so','/etc/a9-autoexec-v54.so','/etc/a9-autoexec-v55.so','/etc/a9-autoexec-v6.so','/etc/a9-autoexec-v61.so','/etc/a9-autoexec-v611.so'}
    require(not old.intersection(tokens),'Old Extra Menu hook is active; restore its own installation before V7.1-MTF2')
    if canonical(HOOK) in tokens:
        raw_tokens=[word for line in before.decode('ascii').splitlines()
                    for word in re.split(r'[\s:]+',line.split('#',1)[0]) if word]
        require(tokens.count(canonical(HOOK))==1 and raw_tokens.count(HOOK)==1,
                'Current hook must appear once using its exact path')
        return before
    return before+(b'\n' if before and not before.endswith(b'\n') else b'')+HOOK.encode()+b'\n'

class FileGuard:
    """Exact file paths and one-shot exact-byte writes; no terminal controls."""
    def __init__(self,transport):
        self.transport=transport;self.initialized=False;self.armed={};self.attempted=set();self.events=[]
    def arm(self,path,target):
        require(path in PATHS and path not in self.armed,'Unknown path or repeated mutation plan')
        require(target is None and path==PRELOAD or isinstance(target,bytes) and len(target)<=MAX_FILE,'Invalid file mutation')
        self.armed[path]=target
    def sendSenserPacket(self,function,data,oData=None):
        require(oData is None and isinstance(data,bytes),'Streaming and nonstandard packets are blocked')
        event={'function':function,'request_bytes':len(data)}
        if function==0x10:
            require(data==struct.pack('<HHB',0,0x1f,0),'Only HASP capability read is allowed')
            event['operation']='HASP'
        elif function==0x40:
            require(len(data)>=4,'Truncated factory read')
            block,code=struct.unpack_from('<HH',data)
            require(block==0x1001,'Only factory file reads are allowed')
            if code==0x4002:
                require(data[4:]==b'\0\0' and not self.initialized,'Repeated/invalid factory file initialization')
                self.initialized=True;event['operation']='file_read_init'
            else:
                require(code==0x4008 and self.initialized and data[4:10]==b'\1\0\0/..' and data[-1:]==b'\0','Invalid factory file read')
                path=data[10:-1].decode('ascii')
                require(path in PATHS,'Factory file path is not fixed')
                event.update(operation='file_presence_read',path=path)
        else:
            require(function==0xff01 and len(data)>=4,'Only FileControl is allowed')
            command,n=struct.unpack_from('<HH',data)
            require(0<n<=256 and n%4==0 and 4+n<=len(data),'Invalid FileControl filename size')
            raw=data[4:4+n];path=raw.rstrip(b'\0').decode('ascii');encoded=path.encode('ascii')
            require(raw==encoded+bytes(4-len(encoded)%4) and path in PATHS,'Invalid FileControl path or padding')
            body=data[4+n:]
            if command==2:require(not body,'Read request has unexpected data')
            else:
                require(path in self.armed and path not in self.attempted,'File mutation not armed or already attempted; no retry')
                target=self.armed[path]
                require(command==3 and target is None and not body or command==1 and isinstance(target,bytes) and body==target,'Mutation differs from exact plan')
                self.attempted.add(path)
            event.update(operation={1:'write',2:'read',3:'delete'}.get(command,'invalid'),path=path)
        self.events.append(event)
        try:
            result=self.transport.sendSenserPacket(function,data)
            event.update(response=result[0],response_bytes=len(result[1]))
            if function==0x40 and event['operation']=='file_presence_read' and len(result[1])>=4:
                event['file_result']=struct.unpack_from('<I',result[1])[0]
            return result
        except Exception as error:
            event['error']=type(error).__name__+': '+str(error);raise

class Files:
    def __init__(self,camera):
        self.camera=camera
        status,raw=camera.dev.sendSenserPacket(0x40,struct.pack('<HH',0x1001,0x4002)+b'\0\0')
        require(status==0 and raw==bytes(4),'Factory file read initialization failed')
    def presence_read(self,path):
        require(path in PATHS,'File path is not fixed')
        status,raw=self.camera.dev.sendSenserPacket(0x40,struct.pack('<HH',0x1001,0x4008)+b'\1\0\0/..'+path.encode()+b'\0')
        require(status==0 and isinstance(raw,bytes) and 4<=len(raw)<=MAX_FILE+4,'Malformed factory file response: '+path)
        result=struct.unpack_from('<I',raw)[0]
        if result==MISSING:
            require(len(raw)==4,'Missing file returned unexpected data');return None
        require(result==0,'File read error '+hex(result)+': '+path)
        return raw[4:]
    def read(self,path):
        raw=self.presence_read(path)
        if raw is not None:
            require(self.camera.readFile(path)==raw,'FileControl readback differs from factory read: '+path)
        return raw

def capture(files,identity,dest):
    rows=[]
    for index,path in enumerate(PATHS):
        raw=files.read(path);require(files.read(path)==raw,'File changed during backup: '+path)
        name='preimage-'+str(index)+'.bin' if raw is not None else None
        if name:save(dest/name,raw)
        rows.append(dict(path=path,exists=raw is not None,file=name,bytes=len(raw) if raw is not None else 0,
                         sha256=sha(raw) if raw is not None else None))
    save_json(dest/'snapshot.json',dict(schema=SCHEMA,identity=identity,files=rows))
    return {row['path']:(dest/row['file']).read_bytes() if row['exists'] else None for row in rows}

def mutate(files,path,target,dest,index):
    save_json(dest/f'mutation-{index}-intent.json',dict(path=path,operation='delete' if target is None else 'write',
        sha256=sha(target) if target is not None else None,automatic_retry=False))
    files.camera.dev.arm(path,target)
    if target is None:
        files.camera.deleteFile(path)
        require(files.presence_read(path) is None,'Deleted preload is still present')
    else:
        files.camera.writeFile(path,target)
        back=files.camera.readFile(path);save(dest/f'readback-{index}.bin',back)
        require(back==target,'FileControl readback mismatch: '+path)
        require(files.presence_read(path)==target,'Factory readback mismatch: '+path)
    save_json(dest/f'mutation-{index}-result.json',dict(verified=True))

def record_failure(dest,camera,stage,error):
    save_json(dest/'failure.json',dict(state='STOPPED_REVIEW_REQUIRED',stage=stage,
        write_attempted=bool(camera.dev.attempted),error=type(error).__name__+': '+str(error),automatic_retry=False))

def install(camera,identity,payloads,session_dir):
    check_identity(identity)
    require(isinstance(payloads,dict) and list(payloads)==list(NAMES),'All three fixed payloads in order are required')
    require(all(isinstance(v,bytes) and 0<len(v)<=MAX_FILE for v in payloads.values()),'Invalid payload data')
    dest=Path(session_dir);dest.mkdir(parents=True,exist_ok=False);stage='file_read_init'
    try:
        files=Files(camera);stage='backup';before=capture(files,identity,dest)
        target_preload=merge_preload(before[PRELOAD])
        targets=dict(zip(TARGETS,payloads.values()))
        for path,target in targets.items():
            require(before[path] is None or before[path]==target,'Existing payload has different bytes; it will not be overwritten: '+path)
        # Preserve the original preload on the camera too, when one existed.
        # An existing backup is never overwritten; the PC snapshot is definitive.
        if before[PRELOAD] is not None and before[PRELOAD]!=target_preload and before[PRELOAD_BACKUP] is None:
            targets={PRELOAD_BACKUP:before[PRELOAD],**targets}
        targets[PRELOAD]=target_preload
        save(dest/'preload-target.bin',target_preload)
        save_json(dest/'intent.json',dict(schema=SCHEMA,identity=identity,action='install',
            preload_target=dict(file='preload-target.bin',sha256=sha(target_preload)),
            files=[dict(path=p,bytes=len(v),sha256=sha(v)) for p,v in targets.items()],
            filecontrol_atomic_rename=False,automatic_retry=False))
        for index,(path,target) in enumerate(targets.items()):
            stage='recheck:'+path
            require(files.read(path)==before[path],'File changed after backup: '+path)
            if before[path]==target:continue
            stage='write:'+path
            mutate(files,path,target,dest,index)
        save_json(dest/'result.json',dict(state='FILES_VERIFIED_BOOT_NOT_TESTED',
            write_attempted=bool(camera.dev.attempted),preload_changed=before[PRELOAD]!=target_preload,
            deactivation_requires_original_session=before[PRELOAD]==target_preload,
            camera_shell_used=False,owner_file_update=False))
        return dest
    except BaseException as error:record_failure(dest,camera,stage,error);raise
    finally:save_json(dest/'protocol.json',dict(events=camera.dev.events,terminal_requests=0))

def load_snapshot(folder,identity):
    folder=Path(folder);meta=json.loads((folder/'snapshot.json').read_text(encoding='utf-8'))
    require(meta.get('schema')==SCHEMA and meta.get('identity')==identity,'Snapshot camera identity differs')
    rows=meta['files'];require([r['path'] for r in rows]==list(PATHS),'Snapshot file paths differ')
    result={}
    for i,row in enumerate(rows):
        if row['exists']:
            require(row['file']==f'preimage-{i}.bin','Snapshot backup filename differs')
            raw=(folder/row['file']).read_bytes()
            require(len(raw)==row['bytes']<=MAX_FILE and sha(raw)==row['sha256'],'Snapshot backup checksum differs')
            result[row['path']]=raw
        else:
            require(row['file'] is None and row['bytes']==0 and row['sha256'] is None,'Invalid absent file snapshot')
            result[row['path']]=None
    return result

def rollback_material(saved_session,identity=None):
    saved=Path(saved_session)
    meta=json.loads((saved/'snapshot.json').read_text(encoding='utf-8'))
    check_identity(meta.get('identity',{}))
    identity=identity or meta['identity']
    before=load_snapshot(saved,identity)
    intent=json.loads((saved/'intent.json').read_text(encoding='utf-8'))
    require(intent.get('schema')==SCHEMA and intent.get('identity')==identity and intent.get('action')=='install','Invalid install intent')
    row=intent['preload_target'];require(row['file']=='preload-target.bin','Invalid preload target filename')
    after=(saved/row['file']).read_bytes();require(sha(after)==row['sha256'],'Preload target checksum differs')
    require(0<len(after)<=16384+len(HOOK)+2,'Invalid preload target size')
    return before,after

def rollback(camera,identity,saved_session,session_dir,*,recover=False):
    check_identity(identity);before,after=rollback_material(saved_session,identity)
    dest=Path(session_dir);dest.mkdir(parents=True,exist_ok=False);stage='rollback_backup'
    try:
        files=Files(camera);current=capture(files,identity,dest)
        require(recover or current[PRELOAD] in (before[PRELOAD],after),'Current preload changed; use --recover only to restore the saved backup deliberately')
        save_json(dest/'intent.json',dict(schema=SCHEMA,identity=identity,action='deactivate',recover=recover,
            payload_files_retained=True,automatic_retry=False))
        if current[PRELOAD]!=before[PRELOAD]:
            stage='restore_preload';require(files.read(PRELOAD)==current[PRELOAD],'Preload changed during rollback')
            mutate(files,PRELOAD,before[PRELOAD],dest,0)
        save_json(dest/'result.json',dict(state='PRELOAD_RESTORED_PAYLOADS_RETAINED',cold_boot_required=True))
        return dest
    except BaseException as error:record_failure(dest,camera,stage,error);raise
    finally:save_json(dest/'protocol.json',dict(events=camera.dev.events,terminal_requests=0))

def validate_runtime(root):
    root=Path(root).resolve();meta=json.loads((root/'runtime_manifest.json').read_text(encoding='utf-8'))
    require(meta.get('schema')=='a9-installer-runtime-v1','Unsupported USB runtime')
    require('src/a9tool/usbdev.py' in meta['files'] and 'src/vendor/pmca/usb/sony.py' in meta['files'],'Incomplete USB runtime')
    for name,digest in meta['files'].items():
        path=(root/name).resolve()
        require(path.is_relative_to(root) and path.is_file() and sha(path.read_bytes())==digest,'USB runtime file differs: '+name)
    return meta

def require_arm_elf(raw,name):
    require(len(raw)>=52 and raw[:7]==b'\x7fELF\1\1\1' and
            struct.unpack_from('<H',raw,18)[0]==40,'Expected ARM ELF: '+name)

def validate_request(raw,op):
    require(len(raw)>=36,'Truncated loader request')
    header=struct.unpack_from('<8I',raw)
    payload=raw[32:];value=2166136261
    for byte in payload:value=((value^byte)*16777619)&0xffffffff
    require(0<len(payload)<=2296 and len(payload)%4==0 and
            header==(0x4d544852,1,op,len(payload),0,value,1184,0),'Invalid loader request header or FNV')
    return payload

def validate_bundle(raw,rows):
    require(isinstance(rows,dict) and set(rows)==set(BUNDLE_NAMES),'Bundle metadata names differ')
    require(len(raw)%512==0 and raw[-1024:]==bytes(1024),'Invalid uncompressed TAR framing')
    entries={}
    try:
        with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as archive:
            for member in archive:
                require(member.name in BUNDLE_NAMES and member.name not in entries and
                        member.isreg() and not member.issparse() and not member.pax_headers,
                        'Bundle member must be a unique fixed regular file: '+member.name)
                row=rows[member.name]
                require(isinstance(row,dict) and set(row)=={'bytes','sha256'} and
                        type(row['bytes']) is int and 0<row['bytes']<=MAX_FILE and
                        re.fullmatch('[0-9a-f]{64}',str(row['sha256'])) is not None,
                        'Invalid bundle file metadata: '+member.name)
                require(member.size==row['bytes'],'Bundle file size differs: '+member.name)
                source=archive.extractfile(member)
                require(source is not None,'Bundle member has no data: '+member.name)
                data=source.read(MAX_FILE+1)
                require(len(data)==row['bytes'] and sha(data)==row['sha256'],
                        'Bundle file checksum/size differs: '+member.name)
                entries[member.name]=data
    except (tarfile.TarError,EOFError) as error:
        raise ValueError('Invalid runtime TAR') from error
    require(set(entries)==set(BUNDLE_NAMES),'Bundle member names differ')
    for name in ('a9-extra-menu.so','a9-extra-menu-guard.elf','a9-wps-boot.elf'):require_arm_elf(entries[name],name)
    for name in ('prepare.sh','runtime-start.sh'):
        require(entries[name].startswith(b'#!/bin/sh\n') and b'\0' not in entries[name] and b'\r' not in entries[name],
                'Expected POSIX shell script with LF lines: '+name)
    payloads=[validate_request(entries[name],op) for op,name in enumerate(('a9-check-persist.req','a9-install-persist.req','a9-remove-persist.req'))]
    require(payloads[0]==payloads[1]==payloads[2],'Loader request payloads differ')
    return entries

def load_package(manifest):
    path=Path(manifest).resolve();meta=json.loads(path.read_text(encoding='utf-8'))
    require(meta.get('schema')=='a9-filecontrol-install-v71mt' and meta.get('model')=='ILCE-9' and meta.get('firmware')=='6.00','Unsupported package')
    require([r['name'] for r in meta['files']]==list(NAMES),'Package payload names differ')
    payloads={}
    for row,target in zip(meta['files'],TARGETS):
        source=(path.parent/row['file']).resolve()
        require(source.is_relative_to(path.parent) and row['path']==target,'Package file escaped fixed path')
        raw=source.read_bytes()
        require(0<len(raw)<=MAX_FILE and len(raw)==row['bytes'] and sha(raw)==row['sha256'],'Package file checksum/size differs: '+row['name'])
        if row['name']==NAMES[0]:require_arm_elf(raw,row['name'])
        payloads[row['name']]=raw
    script=payloads[NAMES[1]]
    require(script.startswith(b'#!/bin/sh\n') and b'\0' not in script and b'\r' not in script,'Expected POSIX autoexec.sh with LF lines')
    validate_bundle(payloads[NAMES[2]],meta.get('bundle_files'))
    return payloads

@contextlib.contextmanager
def connect_runtime(root):
    root=Path(root).resolve();validate_runtime(root)
    sys.path[:0]=[str(root/'src'),str(root/'src/vendor')]
    from a9tool import usbdev
    # A port-bound old receipt cannot prove the current physical body's serial.
    # Every operation starts with fresh MSC identity in this same connection.
    handle=usbdev.connect(receipt=None,guard_factory=FileGuard,response_timeout=120,
        progress=lambda text:print(text,file=sys.stderr))
    try:yield handle.camera,handle.identity
    finally:handle.close()

def main(argv=None):
    base=Path(__file__).resolve().parent
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    for command in ('check','install','backup','status','rollback'):
        sub=commands.add_parser(command)
        sub.add_argument('--runtime',type=Path,default=base/'runtime')
        sub.add_argument('--manifest',type=Path,default=base.parent/'install/manifest.json')
        if command in ('install','backup','rollback'):sub.add_argument('--session',type=Path)
        if command in ('install','rollback'):sub.add_argument('--confirm-write',action='store_true',required=True)
        if command=='rollback':
            sub.add_argument('--from-session',type=Path,required=True)
            sub.add_argument('--recover',action='store_true',help='Restore the saved preload even when its current bytes are damaged or changed')
    args=parser.parse_args(argv)
    payloads=load_package(args.manifest) if args.command in ('check','install') else None
    runtime=validate_runtime(args.runtime)
    if args.command=='check':
        require(not any(n=='usb' or n.startswith('usb.') for n in sys.modules),'USB unexpectedly imported during offline check')
        print(json.dumps(dict(state='PASS_OFFLINE',runtime_files=len(runtime['files']),payloads=len(payloads),
            usb_imported=False,installation_enabled=True,hardware_verified=False,
            hardware_status='NOT_TESTED_V71_MTF2')));return 0
    session=getattr(args,'session',None) or base.parent/'sessions'/(args.command+'-'+time.strftime('%Y%m%d-%H%M%S')+'-'+secrets.token_hex(4))
    if args.command=='rollback':rollback_material(args.from_session)
    if args.command in ('install','backup','rollback'):
        require(not session.exists() and not session.is_symlink(),'Session directory already exists')
        session.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryFile(dir=session.parent):pass
    print('PC session: '+str(session),file=sys.stderr)
    deactivation_requires_original_session=False
    try:
        with connect_runtime(args.runtime) as(camera,identity):
            check_identity(identity)
            if args.command=='install':
                install(camera,identity,payloads,session)
                result=json.loads((session/'result.json').read_text(encoding='utf-8'))
                deactivation_requires_original_session=result['deactivation_requires_original_session']
                if deactivation_requires_original_session:
                    print('V7.1-MTF2 was already active before this install. This session cannot deactivate V7.1-MTF2; '
                          'use the original install session that first added the V7.1-MTF2 preload entry.',file=sys.stderr)
            elif args.command=='rollback':rollback(camera,identity,args.from_session,session,recover=args.recover)
            elif args.command=='backup':
                session.mkdir(parents=True,exist_ok=False);capture(Files(camera),identity,session)
                save_json(session/'protocol.json',dict(events=camera.dev.events,terminal_requests=0))
            else:
                files=Files(camera)
                state={p:files.read(p) for p in PATHS}
                print(json.dumps(dict(identity=identity,files={p:None if v is None else dict(bytes=len(v),sha256=sha(v)) for p,v in state.items()},terminal_requests=0)));return 0
    except BaseException as error:
        if not session.exists():
            session.mkdir(parents=True,exist_ok=False)
            save_json(session/'connection-failure.json',dict(error=type(error).__name__+': '+str(error),write_attempted=False,automatic_retry=False))
        raise
    print(json.dumps(dict(state='COMPLETED_FILE_OPERATIONS_BOOT_NOT_TESTED',session=str(session),terminal_requests=0,
        deactivation_requires_original_session=deactivation_requires_original_session)));return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except (Exception,KeyboardInterrupt) as error:
        print('STOPPED:',type(error).__name__,str(error),file=sys.stderr)
        for note in getattr(error,'__notes__',[]):print(note,file=sys.stderr)
        raise SystemExit(1)
