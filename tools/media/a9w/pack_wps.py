"""Build a fixed A9 WPS.A9W from Sony 32-byte SDS ADPCM inputs, never raw PCM."""
import argparse
import hashlib
import struct
from pathlib import Path
PACK_BYTES=73600
SLOT_BYTES=(24768,29760,18560)
FOUR_SLOT_BYTES=SLOT_BYTES+(9920,)
SLOT_OFFSETS=(512,25280,55040,73600)
def build_package(slots):
    if len(slots) not in (3,4):raise ValueError('three or four optional WPS slots are required')
    version=1 if len(slots)==3 else 2
    size=73600 if version==1 else 83520
    digest=176 if version==1 else 224
    raw=bytearray(size);raw[:8]=b'A9WPS1\0\0'
    mask=sum(1<<i for i,data in enumerate(slots) if data is not None)
    struct.pack_into('<6I',raw,8,version,size,512,mask,0x60009,len(slots))
    for i,(data,n,offset) in enumerate(zip(slots,FOUR_SLOT_BYTES,SLOT_OFFSETS)):
        at=32+48*i;struct.pack_into('<4I',raw,at,0x32 if i==3 else 0x33+i,n,offset,0)
        if data is None:continue
        if len(data)!=n:raise ValueError(f'WPS{i+1} requires exactly {n} encoded bytes; got {len(data)}')
        if any((data[j]>>4)>1 or (data[j]&15)>8 for j in range(0,n,32)):
            raise ValueError(f'WPS{i+1} has invalid Sony 32-byte SDS frame headers')
        raw[offset:offset+n]=data;raw[at+16:at+48]=hashlib.sha256(data).digest()
    raw[digest:digest+32]=hashlib.sha256(raw[:512]+hashlib.sha256(raw[512:]).digest()).digest()
    return bytes(raw)
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for i in range(1,5):parser.add_argument('--wps'+str(i),type=Path)
    parser.add_argument('--restore-stock',action='store_true')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    paths=[getattr(args,'wps'+str(i)) for i in range(1,5)]
    if paths[-1] is None:paths=paths[:3]
    if args.restore_stock==any(paths):parser.error('select encoded WPS files OR --restore-stock')
    try:raw=build_package([p.read_bytes() if p else None for p in paths])
    except (OSError,ValueError) as error:parser.error(str(error))
    args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_bytes(raw)
    print('WPS_PACKAGE_OK bytes='+str(len(raw))+' sha256='+hashlib.sha256(raw).hexdigest())
if __name__=='__main__':main()
