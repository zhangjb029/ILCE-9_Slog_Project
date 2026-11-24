"""Whole-partition transaction with full reads and known ext2 metadata acceptance."""
from pathlib import Path
import hashlib,json,os,time

def digest(data):return hashlib.sha256(data).hexdigest()

def load(path):return json.loads(path.read_text('utf-8'))

def save_new(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())

def save_json(path,obj):save_new(path,(json.dumps(obj,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))

def validate_partition(blob,m):
    if len(blob)!=m['partition_bytes']:raise ValueError('Partition length mismatch')
    if blob[1080:1082]!=b'\x53\xef' or any(blob[:1024]):raise ValueError('Unexpected ext2 image')

def digest_file(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def read_to_file(camera,path,partition):
    """Stream immediately to disk; a failed read retains its partial output."""
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as stream:
        try:camera.readFile(partition,stream)
        finally:stream.flush();os.fsync(stream.fileno())
    return {'sha256':digest_file(path),'bytes':path.stat().st_size}

def load_rollback_session(session):
    """A durable backup and matching intent suffice, even if WRITE failed."""
    session=session.resolve();intent=load(session/'intent.json')
    m={'partition':'/dev/nflasha15','partition_bytes':314572800}
    if intent['partition']!=m['partition']:raise ValueError('Rollback partition differs')
    payload=(session/'preimage.bin').read_bytes();validate_partition(payload,m)
    if digest(payload)!=intent['preimage_sha256']:raise ValueError('Rollback backup hash mismatch')
    identity=intent['identity']
    if identity.get('model')!='ILCE-9' or identity.get('firmware')!='6.00':
        raise ValueError('Rollback identity is not ILCE-9 / 6.00')
    return m,payload,intent

def transfer(camera,payload,m,dest,identity,preflight=None):
    """Save live bytes before checks; record their hash without allowlisting it."""
    validate_partition(payload,m)
    if m['partition']!='/dev/nflasha15':raise ValueError('Unexpected target partition')
    target=digest(payload)
    dest.mkdir(parents=True,exist_ok=False)
    stage='read_preimage';attempted=False
    save_json(dest/'request.json',{'partition':m['partition'],'target_sha256':target,
        'identity':identity,'created_epoch':time.time(),'preimage_hash_policy':'record_only'})
    try:
        snapshot=read_to_file(camera,dest/'preimage.bin',m['partition'])
        save_json(dest/'preimage.json',snapshot)
        if snapshot['bytes']!=m['partition_bytes']:
            raise ValueError('Incomplete live partition read; saved bytes retained; no write sent')
        if preflight is not None:
            prepared=preflight(dest/'preimage.bin')
            if prepared is not None:
                validate_partition(prepared,m)
                payload=prepared
                target=digest(payload)
                save_new(dest/'target.bin',payload)
        save_json(dest/'intent.json',{'partition':m['partition'],'preimage_sha256':snapshot['sha256'],
            'target_sha256':target,'identity':identity,'created_epoch':time.time(),
            'preimage_hash_policy':'record_only'})
        print('Preimage saved:',dest/'preimage.bin',snapshot['sha256'],flush=True)
        if snapshot['sha256']==target:
            save_json(dest/'result.json',{'target_sha256':target,'readback_sha256':target,
                'readback_bytes':snapshot['bytes'],'pass':True,'write_attempted':False,
                'already_at_target':True,'completed_epoch':time.time()})
            print('ALREADY_AT_TARGET; snapshot saved; no write sent');return target
        stage='write'
        save_json(dest/'write_attempt.json',{'target_sha256':target,'started_epoch':time.time()})
        print('Writing once; full preimage is durable.',flush=True)
        attempted=True
        camera.writeFile(m['partition'],payload)
        stage='readback'
        back=read_to_file(camera,dest/'readback.bin',m['partition'])
        details=dict(verified=False,whole_partition_match=False,match_kind='MISMATCH')
        if back['bytes']==len(payload):
            try:
                from .readback_rules import compare_complete
                details=dict(verified=True,whole_partition_match=True,match_kind='EXACT',ext2_changed_offsets=[]) if back['sha256']==target else compare_complete(payload,(dest/'readback.bin').read_bytes())
            except ValueError as error:
                details['reason']=str(error)
        else:details['reason']='Incomplete 300 MiB readback'
        ok=details['verified']
        save_json(dest/'result.json',{'target_sha256':target,'readback_sha256':back['sha256'],
            'readback_bytes':back['bytes'],'pass':ok,'write_attempted':True,
            **details,'completed_epoch':time.time()})
        if not ok:raise ValueError('Post-write readback mismatch; no retry sent; keep the complete/partial session files')
        print('PASS_WRITE_READBACK_'+details['match_kind']+'; cold-start verification is separate.')
        return target
    except BaseException as ex:
        partial=dest/'preimage.bin'
        save_json(dest/'failure.json',{'stage':stage,'write_attempted':attempted,'error':str(ex),
            'preimage_bytes':partial.stat().st_size if partial.exists() else None,
            'preimage_sha256':digest_file(partial) if partial.exists() else None,
            'failed_epoch':time.time()})
        raise

def same_camera(identity,recorded):
    return all(identity.get(k)==recorded.get(k) for k in ['model','firmware','serial_sha256'])
