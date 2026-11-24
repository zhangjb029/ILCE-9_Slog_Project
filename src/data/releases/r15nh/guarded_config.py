"""Four fixed configuration files, durable host snapshots and exact rollback.
No USB import on import. Does not upload or execute a helper.
"""
from pathlib import Path
import hashlib,json,os,struct

PATHS=('/setting/A9FL0.CFG','/setting/A9FL1.CFG','/setting/A9FW0.CFG','/setting/A9FW1.CFG')
PARTITION='/dev/nflasha15'
LUT_IDS=(0x00030004,0x00030005)
MISSING=0x10000006
def require(value,message):
    if not value:raise ValueError(message)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def save(path,raw):
    with Path(path).open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
def save_json(path,value):save(path,(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))

class ConfigGuard:
    def __init__(self,transport,partition_guard,native_send=None):
        self.transport=transport;self.partition_guard=partition_guard
        self.native_send=native_send;self.initialized=False;self.targets=None;self.attempted=set();self.before_partition_write=None
        self.table_targets=None;self.table_attempted=set();self.table_save_allowed=False;self.table_save_attempted=False
    def arm_tables(self,targets):
        require(self.table_targets is None and set(targets)==set(LUT_IDS),'Invalid/repeated LUT restore plan')
        require(all(isinstance(v,bytes) and len(v)==1280 for v in targets.values()),'LUT restore requires two complete tables')
        self.table_targets=dict(targets)
    def arm_table_save(self):
        require(self.table_targets is not None and not self.table_save_attempted,'LUT save cannot be armed')
        self.table_save_allowed=True
    def arm(self,targets):
        require(self.targets is None and set(targets)==set(PATHS),'Invalid/repeated configuration restore plan')
        require(all(v is None or isinstance(v,bytes) and len(v) in (128,512,2048) for v in targets.values()),'Restore requires exact complete records or absence')
        self.targets=dict(targets)
    def sendSenserPacket(self,function,data,oData=None):
        require(isinstance(data,bytes),'Invalid packet')
        if function==0x10 and data==struct.pack('<HHB',0,0x1f,0) and oData is None:
            return self.transport.sendSenserPacket(function,data)
        if function==0x40:
            require(oData is None and len(data)>=4,'Invalid factory request')
            block,code=struct.unpack_from('<HH',data);body=data[4:]
            if block==0x603:
                require(code in (1,2,3),'Unsupported backup operation')
                if code==3:
                    require(body==b'\0\0' and self.table_save_allowed and not self.table_save_attempted,'LUT save is not armed')
                    self.table_save_allowed=False;self.table_save_attempted=True
                else:
                    require(len(body)>=4,'Truncated LUT property request')
                    property_id=struct.unpack_from('<I',body)[0]
                    require(property_id in LUT_IDS,'Only the two FL LUT properties are allowed')
                    if code==1:require(len(body)==4,'Invalid LUT read')
                    else:
                        require(self.table_targets is not None and body[4:]==self.table_targets[property_id],'LUT write differs from restore plan')
                        require(property_id not in self.table_attempted,'LUT write already attempted; no retry')
                        self.table_attempted.add(property_id)
                return self.transport.sendSenserPacket(function,data)
            require(block==0x1001,'Only fixed configuration/LUT requests allowed')
            if code==0x4002:
                require(body==b'\0\0' and not self.initialized,'Repeated factory initialization');self.initialized=True
            elif code==0x4008:
                require(self.initialized and body.startswith(b'\1\0\0/..') and body.endswith(b'\0'),'Invalid factory read')
                require(body[6:-1] in [p.encode('ascii') for p in PATHS],'Configuration path not allowlisted')
            else:raise ValueError('Factory mutations and helper uploads are blocked')
            return self.transport.sendSenserPacket(function,data)
        require(function==0xff01 and len(data)>=4,'Only bounded FileControl and configuration reads allowed')
        cmd,n=struct.unpack_from('<hh',data)
        require(n>0 and n%4==0 and 4+n<=len(data),'Invalid FileControl name length')
        raw=data[4:4+n];name=raw.rstrip(b'\0').decode('ascii')
        encoded=name.encode('ascii');expected=encoded+bytes(4-len(encoded)%4)
        require(raw==expected,'Invalid FileControl path padding')
        if name==PARTITION:
            if cmd==1 and self.before_partition_write:self.before_partition_write()
            return self.partition_guard(function,data,oData)
        require(oData is None and name in PATHS and self.targets is not None,'Configuration write not armed')
        target=self.targets[name];body=data[4+n:]
        require((target is None and cmd==3 and not body) or (target is not None and cmd==1 and body==target),
                'Configuration mutation differs from exact restore plan')
        require(name not in self.attempted,'Configuration mutation already attempted; no retry')
        self.attempted.add(name)
        if self.native_send:return self.native_send(function,data,oData)
        from pmca.usb import sony
        return sony.SonySenserDevice.sendSenserPacket(self.transport,function,data,oData)

def load_snapshot(folder,identity):
    folder=Path(folder);m=json.loads((folder/'snapshot.json').read_text('utf-8'))
    require(m.get('schema')=='a9-fl23-config-snapshot-v1' and m.get('identity')==identity,'Configuration snapshot identity differs')
    rows=m.get('files',[]);require([r['path'] for r in rows]==list(PATHS),'Configuration snapshot paths differ')
    result={}
    for i,row in enumerate(rows):
        if row['exists']:
            require(row['file']=='config-'+str(i)+'.bin','Snapshot file path differs')
            raw=(folder/row['file']).read_bytes()
            require(len(raw)==row['bytes']<=2049 and sha(raw)==row['sha256'],'Configuration snapshot hash differs')
            result[row['path']]=raw
        else:
            require(row.get('file') is None and row['bytes']==0 and row.get('sha256') is None,'Malformed absent configuration record')
            result[row['path']]=None
    return result

class Configuration:
    def __init__(self,camera):
        self.camera=camera;self.identity={}
        status,raw=camera.dev.sendSenserPacket(0x40,struct.pack('<HH',0x1001,0x4002)+b'\0\0')
        require(status==0 and raw==bytes(4),'Factory read initialization failed')
    def read(self,path):
        require(path in PATHS,'Unknown configuration path')
        status,raw=self.camera.dev.sendSenserPacket(0x40,struct.pack('<HH',0x1001,0x4008)+b'\1\0\0/..'+path.encode()+b'\0')
        require(status==0 and isinstance(raw,bytes) and 4<=len(raw)<=2053,'Malformed configuration response')
        result=struct.unpack_from('<I',raw)[0]
        if result==MISSING:
            require(len(raw)==4,'Data returned for missing configuration');return None
        require(result==0,'Configuration read error: '+hex(result));return raw[4:]
    def capture(self,folder,identity):
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=False);rows=[];self.identity=identity
        for i,path in enumerate(PATHS):
            raw=self.read(path);name='config-'+str(i)+'.bin' if raw is not None else None
            if name:save(folder/name,raw)
            require(self.read(path)==raw,'Configuration changed during bounded capture: '+path)
            rows.append(dict(path=path,exists=raw is not None,file=name,bytes=len(raw) if raw is not None else 0,sha256=sha(raw) if raw is not None else None))
        result=dict(schema='a9-fl23-config-snapshot-v1',identity=identity,files=rows)
        save_json(folder/'snapshot.json',result);return result
    def unchanged(self,targets):
        require(all(self.read(p)==targets[p] for p in PATHS),'Configuration changed before partition operation')
    def restore(self,targets,folder):
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
        self.capture(folder/'before',self.identity);before=load_snapshot(folder/'before',self.identity)
        self.camera.dev.arm(targets)
        results=[]
        for i,path in enumerate(PATHS):
            target=targets[path]
            require(self.read(path)==before[path],'Configuration changed before restore: '+path)
            if target==before[path]:results.append(dict(path=path,write_attempted=False));continue
            save_json(folder/('write-intent-'+str(i)+'.json'),dict(path=path,command='delete' if target is None else 'write',
                before_sha256=sha(before[path]) if before[path] is not None else None,target_sha256=sha(target) if target is not None else None,automatic_retry=False))
            if target is None:self.camera.deleteFile(path)
            else:self.camera.writeFile(path,target)
            require(self.read(path)==target,'Configuration restore readback differs: '+path)
            results.append(dict(path=path,write_attempted=True))
        self.unchanged(targets)
        save_json(folder/'result.json',dict(verified=True,files=results))
        return results
