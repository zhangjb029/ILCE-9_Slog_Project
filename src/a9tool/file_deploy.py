"""Durable file transactions and a fixed, bounded service-terminal adapter.

R15 callers must separately establish the stable-owner/snapshot protocol before
calling commit. This generic engine does not claim process or multi-file atomicity.
"""
import json
import contextlib
import io
import os
import re
import struct
import time
import uuid
from pathlib import Path

from .release_assets import sha

R15_PATHS = ('/usr/lib/a9fl.so', '/usr/lib/viewUnified2.so',
             '/usr/lib/CautionConfig.so', '/usr/share/app/string_english.uxc',
             '/usr/share/app/string_simplifiedchinese.uxc')
CONFIG_PATHS = tuple('/setting/'+n+'.CFG' for n in ('A9FL0','A9FL1','A9FW0','A9FW1'))
MAX_FILE = 32*1024*1024


def identity_key(identity):
    """USB topology is session evidence, never part of physical body identity."""
    from .usbdev import check_identity
    check_identity(identity)
    return {name: identity[name] for name in ('model','firmware','serial_sha256')}


def durable(path, raw):
    with Path(path).open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if Path(path).read_bytes() != raw:
        raise IOError('Local durable file readback differs')
    _sync_directory(Path(path).parent)


def _sync_directory(folder):
    if os.name != 'nt':
        fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)


def save_record(folder, record):
    folder = Path(folder)
    temp = folder/'transaction.next'
    with temp.open('w', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    os.replace(temp, folder/'transaction.json')
    _sync_directory(folder)


def load_transaction(folder):
    folder = Path(folder)
    record = json.loads((folder/'transaction.json').read_text(encoding='utf-8'))
    if record.get('schema') != 'a9-file-transaction-v1':
        raise ValueError('Unknown file transaction schema')
    seen = set()
    for index, row in enumerate(record['files']):
        if row['path'] not in R15_PATHS or row['path'] in seen or row['index'] != index:
            raise ValueError('Invalid transaction fixed path')
        seen.add(row['path'])
        for key in ('before','target'):
            digest = row[key+'_sha256']
            if digest is not None:
                raw = (folder/f'{index}-{key}.bin').read_bytes()
                if len(raw) > MAX_FILE or sha(raw) != digest:
                    raise ValueError('Transaction backup/target checksum differs')
    return record


def prepare_transaction(files, identity, root, targets):
    identity=identity_key(identity)
    if not targets or not set(targets) <= set(R15_PATHS):
        raise ValueError('Unknown installation paths')
    if any(v is not None and (not isinstance(v,bytes) or not 0<len(v)<=MAX_FILE) for v in targets.values()):
        raise ValueError('Invalid complete target file')
    folder = Path(root)/('files-'+uuid.uuid4().hex)
    folder.mkdir(parents=True)
    record = dict(schema='a9-file-transaction-v1', identity=identity,
                  state='PREPARED', files=[], automatic_retry=False)
    for index,(path,target) in enumerate(targets.items()):
        before = files.read(path)
        if before is not None:
            if len(before)>MAX_FILE: raise ValueError('Source file oversized')
            durable(folder/f'{index}-before.bin', before)
        if target is not None: durable(folder/f'{index}-target.bin', target)
        if files.read(path) != before:
            raise ValueError('Source changed during backup')
        record['files'].append(dict(index=index,path=path,
            before_sha256=sha(before) if before is not None else None,
            target_sha256=sha(target) if target is not None else None))
    save_record(folder, record)
    return folder


def _blob(folder, row, kind):
    return None if row[kind+'_sha256'] is None else (Path(folder)/f"{row['index']}-{kind}.bin").read_bytes()


def _identity(record, identity):
    if identity_key(record['identity']) != identity_key(identity):
        raise ValueError('Transaction camera identity differs')


def _apply(files, folder, record, kind):
    try:
        for row in record['files']:
            path = row['path']; target = _blob(folder,row,kind)
            observed = files.read(path)
            if observed == target: continue
            record.update(state='MUTATION_PENDING', current_path=path)
            save_record(folder,record)  # before any upload or terminal operation
            if target is None:
                files.delete(path)
            else:
                stage = path+'.a9tool-stage'
                files.write(stage,target)
                back = files.read(stage)
                durable(Path(folder)/f"{row['index']}-{kind}-stage-{uuid.uuid4().hex}.bin",back)
                if back != target: raise ValueError('Staged file readback differs')
                files.sync()
                if files.read(path) != observed:
                    raise ValueError('Source changed while staging; replacement stopped')
                files.replace(stage,path)
            files.sync()
            back = files.read(path)
            if back != target: raise ValueError('Final file readback differs')
            if back is not None:
                durable(Path(folder)/f"{row['index']}-{kind}-final-{uuid.uuid4().hex}.bin",back)
        record.update(state='FILES_VERIFIED_ACTIVATION_PENDING' if kind=='target' else 'ORIGINAL_FILES_RESTORED', current_path=None)
        save_record(folder,record)
    except BaseException as error:
        record.update(state='RESULT_UNKNOWN',error=type(error).__name__+': '+str(error))
        save_record(folder,record)
        raise


def commit_transaction(files, folder, identity):
    record = load_transaction(folder); _identity(record,identity)
    if record['state'] != 'PREPARED':
        raise ValueError('Transaction requires recovery; automatic replay refused')
    for row in record['files']:
        if files.read(row['path']) != _blob(folder,row,'before'):
            raise ValueError('Source changed after preparation')
    _apply(files,folder,record,'target')
    return record


def restore_transaction(files, folder, identity):
    record = load_transaction(folder); _identity(record,identity)
    # A failed upload/rename is resolved by fresh reads, never by replaying install.
    for row in record['files']:
        live = files.read(row['path'])
        if live not in (_blob(folder,row,'before'),_blob(folder,row,'target')):
            raise ValueError('Current file is neither original nor target; recovery stopped')
    _apply(files,folder,record,'before')
    return record


class ReadGuard:
    """R15 file/config/two-table reads only; no memory, writes, or terminal."""
    def __init__(self, transport):
        self.transport=transport; self.initialized=False

    def sendSenserPacket(self,function,data,oData=None):
        allowed = function==0x10 and data==struct.pack('<HHB',0,0x1f,0)
        if function==0x40 and len(data)>=4:
            block,cmd=struct.unpack_from('<HH',data); body=data[4:]
            if block==0x603:
                allowed=oData is None and cmd==1 and len(body)==4 and int.from_bytes(body,'little') in (0x30004,0x30005)
            elif block==0x1001 and cmd==0x4002:
                allowed=oData is None and body==b'\0\0' and not self.initialized
                if allowed: self.initialized=True
            elif block==0x1001 and cmd==0x4008:
                allowed=self.initialized and body.startswith(b'\1\0\0/..') and body.endswith(b'\0') and body[6:-1].decode('ascii') in R15_PATHS+CONFIG_PATHS
        if function==0xff01 and len(data)>=4:
            cmd,n=struct.unpack_from('<HH',data); raw=data[4:4+n]
            name=raw.rstrip(b'\0').decode('ascii')
            allowed=cmd==2 and n>0 and len(data)==4+n and raw==name.encode()+bytes(4-len(name)%4) and name in R15_PATHS+CONFIG_PATHS
        if not allowed: raise ValueError('R15 packet outside read allowlist')
        return self.transport.sendSenserPacket(function,data,oData)


class CameraFiles:
    def __init__(self,camera):
        self.camera=camera
        status,raw=camera.dev.sendSenserPacket(0x40,struct.pack('<HH',0x1001,0x4002)+b'\0\0')
        if status!=0 or raw!=bytes(4): raise ValueError('File presence initialization failed')

    def read(self,path):
        sink=BoundedSink(MAX_FILE+4)
        status,_=self.camera.dev.sendSenserPacket(0x40,struct.pack('<HH',0x1001,0x4008)+b'\1\0\0/..'+path.encode('ascii')+b'\0',sink)
        raw=sink.getvalue()
        if status!=0 or not isinstance(raw,bytes) or not 4<=len(raw)<=MAX_FILE+4:
            raise ValueError('Invalid file presence response')
        result=int.from_bytes(raw[:4],'little')
        if result==0x10000006 and len(raw)==4: return None
        if result!=0: raise ValueError('File presence read failed')
        sink=BoundedSink(MAX_FILE)
        self.camera.readFile(path,sink)
        back=sink.getvalue()
        if back != raw[4:]: raise ValueError('FileControl differs from presence read')
        return back


class BoundedSink(io.BytesIO):
    def __init__(self,limit):
        super().__init__(); self.limit=limit

    def write(self,data):
        if self.tell()+len(data)>self.limit:
            raise ValueError('Streamed file exceeds allowed size')
        return super().write(data)


class FixedTerminal:
    """No arbitrary command API. Construct only after a reviewed write guard.

    The adapter uses the existing authenticated Senser session. A timeout is
    unknown and never retries. It does not establish a stable FL owner window.
    """
    def __init__(self,camera,timeout=15):
        self.camera=camera; self.transport=camera.dev.transport; self.timeout=timeout

    def _run(self,command):
        marker='A9TX_'+uuid.uuid4().hex
        script=command+"; a9tx_rc=$?; printf '\\n"+marker+":%s\\n' \"$a9tx_rc\"\n"
        self.camera.setTerminalEnable(True)
        try:
            self.transport.writeTerminal(script.encode('ascii'))
            raw=b''; deadline=time.monotonic()+self.timeout
            pattern=re.compile(rb'\r?\n'+marker.encode()+rb':([0-9]+)\r?\n')
            while time.monotonic()<deadline:
                raw+=self.transport.readTerminal()
                if len(raw)>1024*1024: raise ValueError('Terminal response too large')
                match=pattern.search(raw)
                if match:
                    if match[1]!=b'0': raise RuntimeError('Fixed service operation failed')
                    return raw[:match.start()]
            raise TimeoutError('Fixed service operation result unknown; no retry')
        finally:
            self.camera.setTerminalEnable(False)

    def inspect(self):
        return self._run('cat /proc/mounts; df -k /usr; stat -c "%a %u %g %s" /usr/lib/a9fl.so')

    def mount_state(self):
        raw=self._run('cat /proc/mounts')
        rows=[line.split() for line in raw.decode('ascii').splitlines()]
        rows=[row for row in rows if len(row)>=4 and row[1]=='/usr']
        if len(rows)!=1 or rows[0][0]!='/dev/nflasha15' or rows[0][2]!='ext2':
            raise ValueError('Unexpected /usr filesystem; no remount')
        modes=set(rows[0][3].split(','))
        if len(modes & {'ro','rw'})!=1: raise ValueError('Ambiguous mount state')
        return 'ro' if 'ro' in modes else 'rw'

    @contextlib.contextmanager
    def mounted_for_update(self):
        original=self.mount_state()
        if original=='ro': self.writable()
        try:
            if self.mount_state()!='rw': raise ValueError('Writable mount verification failed')
            yield
        finally:
            self.sync()
            if original=='ro': self.readonly()
            if self.mount_state()!=original:
                raise RuntimeError('Original mount state restoration not verified')

    def writable(self):
        return self._run('mount -o remount,rw /usr')

    def readonly(self):
        return self._run('sync && mount -o remount,ro /usr')

    def replace(self,stage,target):
        if target not in R15_PATHS or stage!=target+'.a9tool-stage':
            raise ValueError('Non-fixed replacement path')
        # Numeric metadata avoids GNU-only chmod/chown --reference switches.
        meta=self._run('stat -c "%a %u %g" '+target)
        lines=[line.strip() for line in meta.decode('ascii').splitlines() if re.fullmatch(r'[0-7]{3,4} [0-9]+ [0-9]+',line.strip())]
        if len(lines)!=1: raise ValueError('File metadata response ambiguous')
        mode,uid,gid=lines[0].split()
        # cp -p retains an on-body original; target is only replaced after sync.
        return self._run('test -f '+target+' && test ! -e '+target+'.a9tool-original && cp -p '+target+' '+target+'.a9tool-original && chmod '+mode+' '+stage+' && chown '+uid+':'+gid+' '+stage+' && sync && mv -f '+stage+' '+target)

    def sync(self): return self._run('sync')

    def delete(self,path):
        if path not in R15_PATHS: raise ValueError('Non-fixed deletion path')
        return self._run('rm -f '+path+' && sync')
