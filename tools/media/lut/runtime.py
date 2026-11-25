"""Portable data adapter for the unchanged R15 fitting modules."""
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ[key]='1'
sys.path.insert(0,str(ROOT.parents[2]/'src'))


def checked_data(name):
    path=ROOT/'data'/name
    expected=json.loads((ROOT/'data/SHA256SUMS.json').read_text('utf-8'))[name]
    if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
        raise ValueError('Frozen input changed: '+name)
    return path


def inputs():
    import numpy as np
    from a9tool.release_a9p import stock
    curves=json.loads(checked_data('chroma_curves.json').read_text('utf-8'))
    return stock(),np.asarray(curves['a7_pkg_expand']),np.asarray(curves['a7_pkg_compress'])
