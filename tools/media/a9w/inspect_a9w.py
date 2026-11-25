"""Inspect canonical A9W V1/V2 by re-encoding with the frozen packer."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
from pack_wps import build_package,FOUR_SLOT_BYTES,SLOT_OFFSETS


def inspect(raw):
    if len(raw) not in (73600,83520):raise ValueError('Expected exact A9W V1/V2 size')
    version,total,header,mask,model,count=struct.unpack_from('<6I',raw,8)
    if (version,count,len(raw)) not in ((1,3,73600),(2,4,83520)):
        raise ValueError('Version/slot count/size mismatch')
    slots=[raw[offset:offset+size] if mask&(1<<i) else None
           for i,(offset,size) in enumerate(zip(SLOT_OFFSETS[:count],FOUR_SLOT_BYTES[:count]))]
    if raw!=build_package(slots):raise ValueError('Header, reserved bytes, mask, slot or package SHA256 mismatch')
    return dict(version=version,bytes=total,header=header,mask=mask,model=hex(model),
        sha256=hashlib.sha256(raw).hexdigest(),slots=[dict(slot=i+1,app_id=hex(0x32 if i==3 else 0x33+i),
            selected=data is not None,bytes=FOUR_SLOT_BYTES[i],frames=FOUR_SLOT_BYTES[i]//32,
            samples=FOUR_SLOT_BYTES[i]//32*31,
            sha256=hashlib.sha256(data).hexdigest() if data is not None else None) for i,data in enumerate(slots)])


if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__);cli.add_argument('input',type=Path)
    args=cli.parse_args()
    try:print(json.dumps(inspect(args.input.read_bytes()),indent=2))
    except (OSError,ValueError) as error:cli.exit(1,str(error)+'\n')
