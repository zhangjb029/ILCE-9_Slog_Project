"""Build R12P byte-run deltas from formal external images; distribute no image.

The target and every source stay outside the release. Output contains only
changed-byte runs, pinned source identities and named source metadata values.
"""
import argparse
import hashlib
import json
import lzma
import struct
import sys
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'src'))
from a9tool.menu_deploy import _apply

SIZE=314572800
TARGET='704d9401fb8f63823ffde6a8812eda38ae27d81d6432bf8332cdad95e46233da'


def sha(raw):return hashlib.sha256(raw).hexdigest()


def make_runs(source,target):
    runs=[];begin=None;data=bytearray()
    for page in range(0,len(source),65536):
        a,b=source[page:page+65536],target[page:page+65536]
        if a==b:
            if begin is not None:runs.append((begin,bytes(data)));begin=None;data.clear()
            continue
        for i,(old,new) in enumerate(zip(a,b)):
            if old!=new:
                if begin is None:begin=page+i
                data.append(new)
            elif begin is not None:
                runs.append((begin,bytes(data)));begin=None;data.clear()
    if begin is not None:runs.append((begin,bytes(data)))
    return runs


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--analysis-root',type=Path,required=True)
    ap.add_argument('--target',type=Path)
    args=ap.parse_args();base=args.analysis_root.resolve()
    target_path=args.target or base/'a9_fl_r15_name_only_20261121/operator/nflasha15_FL43_SD_R15.bin'
    target=target_path.read_bytes()
    if len(target)!=SIZE or sha(target)!=TARGET:raise ValueError('Formal target identity differs')
    paths={
        'stock':'a9_v600/firmware.tar_unpacked/0700_part_image/dev/nflasha15',
        'R8':'a9_fl_full_partition_20261113_R8/nflasha15_FL_R8.bin',
        'R9':'a9_fl23_operator_20261114_R9/nflasha15_FL23_R9.bin',
        'R9.1':'a9_fl23_operator_20261115_R91/nflasha15_FL23_R91.bin',
        'R10':'a9_fl20_r10_20261115/operator/nflasha15_FL20_R10.bin',
        'R11':'a9_fl23_film_r12_20261115/operator/nflasha15_FL20_MENU_R11.bin',
        'R12':'a9_fl23_film_r12_20261115/operator/nflasha15_FL23_FILM_R12.bin',
    }
    output=REPO/'src/data/releases/r15nh'
    manifest=json.loads((output/'manifest.json').read_text('utf-8'))
    rows={r['label']:r for r in manifest['sources']};sources=[];validation=[]
    for label,relative in paths.items():
        source=(base/relative).read_bytes();file_size=len(source);source+=bytes(SIZE-len(source))
        row=dict(rows[label])
        if sha(source)!=row['canonical_sha256']:raise ValueError('Formal source differs: '+label)
        runs=make_runs(source,target);raw=bytearray(b'R12P'+struct.pack('<I',len(runs)));previous=0
        for offset,after in runs:
            raw.extend(struct.pack('<II',offset-previous,len(after)));raw.extend(after);previous=offset
        patch=lzma.compress(raw,preset=6)
        name=label.lower().replace('.','_')+'.r12p.xz';(output/name).write_bytes(patch)
        if _apply(source,runs)!=target:raise ValueError('Local patch reconstruction failed: '+label)
        changed=sum(len(after)for _,after in runs)
        # A delta must contain a small subset of image bytes, never a wrapped
        # complete partition masquerading as a patch.
        if changed>=SIZE//10:raise ValueError('Delta exceeds the declared changed-byte scope')
        row['patch']=name;row['patch_statistics']=dict(offset_runs=len(runs),changed_bytes=changed,
            uncompressed_patch_bytes=len(raw),compressed_patch_bytes=len(patch),patch_sha256=sha(patch))
        row['canonical_metadata']=[dict(start=a,end=b,hex=source[a:b].hex())for a,b in row['normalization_regions']]
        sources.append(row)
        validation.append(dict(source_label=label,source_file_bytes=file_size,source_partition_bytes=SIZE,
            source_partition_sha256=sha(source),target_bytes=SIZE,target_sha256=TARGET,passed=True,**row['patch_statistics']))
        print(label+': '+json.dumps(row['patch_statistics']),flush=True)
    # Current NAME HELP can be recognized but is never re-patched/reflashed.
    sources.append(rows['R15 NAME HELP'])
    manifest.update(schema='a9-r15nh-r12p-release-v2',sources=sources,
                    workflow='backup -> identify -> local R12P patch -> one full FF01 write -> complete readback')
    manifest['files']={}
    for path in sorted(output.iterdir()):
        if path.is_file() and path.name not in ('manifest.json','target.bin.xz'):
            payload=path.read_bytes();manifest['files'][path.name]=dict(bytes=len(payload),sha256=sha(payload))
    encoded=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    (output/'manifest.json').write_bytes(encoded)
    receipt=dict(schema='a9-r15nh-offline-r12p-validation-v2',evidence_type='offline formal-image delta generation and exact reconstruction',
        hardware_verified=False,cold_boot_verified=False,camera_access=False,
        scope='Each source was read externally, padded only for stock, diffed against the fixed target, and reconstructed using menu_deploy._apply. No complete image is distributed.',
        rows=validation)
    (REPO/'docs/r15nh-source-validation.json').write_text(json.dumps(receipt,indent=2)+'\n','utf-8')
    print('manifest_sha256='+sha(encoded),flush=True)


if __name__=='__main__':main()
