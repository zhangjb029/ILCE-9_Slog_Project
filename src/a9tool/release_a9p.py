"""Build/inspect named A9P V2 from *native* source tables (not .cube samples)."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import zlib

ROOT = Path(__file__).resolve().parent
SHA = bytes.fromhex('d4a9a6234f6c05083716fb9cb1218d7e50ef541a0a279ac0a61b786a73822d1b')
BUILD = b'37111_13.2019091301'.ljust(24, b'\0')
MIN = (-9,-9,-9,0,-9,-3,1,0,0,-9,-9,-9,-9,-9,-9,-9)
MAX = (9,9,9,9,9,3,5,9,9,9,9,9,9,9,9,9)
DEFAULT = bytes(6) + b'\x01' + bytes(9)


def stock():
    from .release_assets import asset
    pair = tuple(asset('r15/stock'+str(i)+'.bin') for i in range(2))
    if hashlib.sha256(b''.join(pair)).digest() != SHA:
        raise ValueError('stock source identity changed')
    return pair


def name_bytes(name):
    wspace = {0x20,0xa0,0x1680,0x202f,0x205f,0x3000,*range(0x2000,0x200b)}
    denied = {*range(0x20),*range(0x7f,0xa0),0x061c,0x200e,0x200f,*range(0x2028,0x202f),
              *range(0x2066,0x206a),0xfeff,*range(0xfdd0,0xfdf0)}
    raw = name.encode('utf-8',errors='strict')
    if not 1 <= len(raw) <= 64 or ord(name[0]) in wspace or ord(name[-1]) in wspace:
        raise ValueError('name must have 1–64 UTF-8 bytes and no leading/trailing whitespace')
    if any(ord(c) in denied or (ord(c)&0xffff)>=0xfffe for c in name):
        raise ValueError('name contains an unsupported Unicode character')
    return raw


def inputs(pair):
    result = []
    for t,(data,base) in enumerate(zip(pair,stock(),strict=True)):
        if len(data)!=1280 or data[1215:]!=base[1215:]:
            raise ValueError(f'table {t}: expected 1280 bytes and matching factory calibration tail')
        v = [c if c<128 else c-256 for c in data[:1215]]
        for i,a in enumerate(v):
            if not -64<=a<=63:
                raise ValueError(f'table {t}: node {i} outside native signed7 [-64,63]')
        for col in range(81):
            samples = [max(0,min(256,64*r+v[r*81+col])) for r in range(5)]
            if samples!=sorted(samples):
                raise ValueError(f'table {t}: nonmonotonic luma column {col}')
        result.append(data)
    return b''.join(result)


def encode(name,pair,defaults=None):
    n = name_bytes(name)
    tables = inputs(pair)
    if defaults is not None and (len(defaults)!=16 or any(not a<=v<=b for v,a,b in zip(defaults,MIN,MAX))):
        raise ValueError('invalid 16 defaults (see --help and README)')
    header = struct.pack('<8sHHI8s24s32sIIHHI16sH14x64s',b'A9FLPK2\0',2,192,2756,b'ILCE-9',BUILD,SHA,
                         0x30004,0x30005,1280,1280,int(defaults is not None),
                         struct.pack('<16b',*defaults) if defaults is not None else bytes(16),len(n),n)
    body = header+tables
    return body+struct.pack('<I',zlib.crc32(body))


def inspect(raw):
    if len(raw)==2692 and raw.startswith(b'A9FLPK1\0'):
        raise ValueError('V1 is unnamed; re-export a V2 package')
    if len(raw)!=2756:
        raise ValueError('size must be 2756 bytes')
    size = int.from_bytes(raw[112:114],'little')
    if not 1<=size<=64:
        raise ValueError('invalid name length')
    name = raw[128:128+size].decode('utf-8',errors='strict')
    defaults = struct.unpack_from('<16b',raw,96) if raw[92:96]==b'\x01\0\0\0' else None
    if raw!=encode(name,(raw[192:1472],raw[1472:2752]),defaults):
        raise ValueError('structure, identity, padding or CRC mismatch')
    return {'name':name,'bytes':len(raw),'sha256_payload':hashlib.sha256(raw[:2752]).hexdigest(),
            'table_sha256':[hashlib.sha256(raw[o:o+1280]).hexdigest() for o in (192,1472)],
            'controls':defaults or tuple(DEFAULT)}


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    subs=cli.add_subparsers(dest='cmd',required=True)
    out=subs.add_parser('export');out.add_argument('--name',required=True)
    out.add_argument('--table0',type=Path,required=True);out.add_argument('--table1',type=Path,required=True)
    out.add_argument('--defaults',nargs=16,type=int)
    out.add_argument('output',type=Path)
    info=subs.add_parser('inspect');info.add_argument('input',type=Path)
    ns=cli.parse_args()
    try:
        if ns.cmd=='export':
            raw=encode(ns.name,(ns.table0.read_bytes(),ns.table1.read_bytes()),ns.defaults)
            with ns.output.open('xb') as stream: stream.write(raw)
        else: raw=ns.input.read_bytes()
        print(json.dumps(inspect(raw),ensure_ascii=False,indent=2))
    except (OSError,ValueError) as exc:
        cli.exit(1,f'{exc}\n')


if __name__=='__main__': main()
