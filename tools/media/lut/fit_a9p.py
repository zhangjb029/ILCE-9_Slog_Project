"""Portable CLI around the frozen R15/227-library fitting recipes; PC only."""
import argparse
import hashlib
import json
from pathlib import Path
import runtime as rt  # sets the original single-thread numeric environment first
import numpy as np
import a9_model as a9
from fit_metrics import context,statistics
from lut import Cube,reference,PRIMARIES
from refine import refine_table
from a9tool import release_a9p as a9p


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fit(args):
    a9p.name_bytes(args.name)
    if args.out.exists():raise FileExistsError('Output directory must be new')
    if not np.isfinite(args.exposure_scale) or args.exposure_scale<=0:
        raise ValueError('Exposure scale must be finite and positive')
    builtin=args.recipe=='builtin'
    if builtin and (args.targets is None or args.prior_pair is None):
        raise ValueError('The frozen builtin recipe requires --targets and --prior-pair')
    baseline=rt.checked_data('baseline.npz')
    base=np.load(baseline,allow_pickle=False)
    stock,expand,_=rt.inputs()
    train=np.flatnonzero(base['split']=='train');valid=np.flatnonzero(base['split']=='valid');test=np.flatnonzero(base['split']=='test')
    special=train[base['kind'][train]!='uniform_luma'];regular=train[base['kind'][train]=='uniform_luma']
    chosen=np.sort(np.r_[special,np.random.default_rng(20261115 if builtin else 20261121).choice(
        regular,min(16000,len(regular)) if builtin else 12000,replace=False)])
    refined=np.sort(np.random.default_rng(20261116 if builtin else 20261122).choice(
        train,8192 if builtin else 6144,replace=False))
    steps=args.steps if args.steps is not None else (240 if builtin else 200)
    if steps<0:raise ValueError('Steps must be nonnegative')
    # R15 intentionally uses the complete native signed7 range, as did the
    # original two fitting entry points. The model module itself is unchanged.
    a9.limits=lambda unused:(np.full(1215,-64,dtype=int),np.full(1215,63,dtype=int))
    spec=dict(input_gamut=args.input_gamut,input_curve=args.input_curve,
              output_gamut=args.output_gamut,output_curve=args.output_curve,
              exposure_scale=args.exposure_scale)
    cube=Cube.parse(args.cube.read_text('utf-8-sig')) if args.cube else None
    targets=np.load(args.targets,allow_pickle=False) if args.targets else None
    prior=args.prior_pair.read_bytes() if args.prior_pair else None
    if prior is not None and len(prior)!=2560:raise ValueError('Prior pair must be 2560 bytes, table0 then table1')
    pair=[];reports=[]
    for table in range(2):
        at,w,anchor,model=context(stock[table],base[f'table{table}'],expand)
        target=targets[f'photo{table}'] if targets is not None else reference(cube,base[f'table{table}'],table,spec)
        if target.shape!=base[f'table{table}'].shape or not np.isfinite(target).all():
            raise ValueError('Target arrays must match the complete frozen sample order')
        def metrics(raw,rows):
            return statistics(target[rows],a9.decode_compressed(w[rows]@a9.node_outputs(raw)+anchor[rows],expand),table)
        def score(raw):
            stats=metrics(raw,valid);return stats['deltaE00_mean']+.1*stats['deltaE00_p95']
        initial,info,_=a9.fit(at[chosen],target[chosen],stock[table],expand,
            (a9.compressed(target,expand)-anchor)[chosen])
        previous=prior[table*1280:(table+1)*1280] if prior is not None else stock[table]
        a9p.inputs((previous,stock[1]) if table==0 else (stock[0],previous))
        initial=min((previous,initial),key=score)
        raw,detail=refine_table(initial,stock[table],at[refined],anchor[refined],target[refined],expand,
            table,steps=steps,validation=(at[valid],w[valid],anchor[valid],target[valid]))
        pair.append(raw)
        reports.append(dict(table=table,sha256=hashlib.sha256(raw).hexdigest(),fit=info,refinement=detail,
            validation=metrics(raw,valid),held_out=metrics(raw,test),factory_to_target=metrics(stock[table],test),model=model))
    package=a9p.encode(args.name,tuple(pair));inspection=a9p.inspect(package)
    args.out.mkdir(parents=True,exist_ok=False)
    card=args.out/'CARD/PRIVATE/A9FL';card.mkdir(parents=True)
    for table,raw in enumerate(pair):(args.out/f'0003000{4+table}.bin').write_bytes(raw)
    (card/'LUT1.A9P').write_bytes(package)
    report=dict(name=args.name,recipe=args.recipe,steps=steps,encoding=spec,tables=reports,
        source_sha256=sha(args.cube or args.targets),prior_pair_sha256=sha(args.prior_pair) if prior is not None else None,
        baseline_sha256=sha(baseline),a9p=inspection,package_sha256=hashlib.sha256(package).hexdigest(),
        samples=dict(train=len(chosen),refine=len(refined),validation=len(valid),held_out_test=len(test)),
        test_used_for_selection=False,camera_access=False,
        model='Frozen experimental Y/compressed-chroma model; not bit-exact ISP')
    (args.out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--cube',type=Path);source.add_argument('--targets',type=Path)
    parser.add_argument('--name',required=True);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--recipe',choices=('library','builtin'),default='library')
    parser.add_argument('--prior-pair',type=Path);parser.add_argument('--steps',type=int)
    parser.add_argument('--input-gamut',choices=PRIMARIES,default='srgb')
    parser.add_argument('--input-curve',choices=('srgb','linear','adobe','gamma22','gamma24','prophoto','vlog','flog','flog2','nlog'),default='srgb')
    parser.add_argument('--output-gamut',choices=PRIMARIES,default='srgb')
    parser.add_argument('--output-curve',choices=('srgb','linear','adobe','gamma22','gamma24','prophoto'),default='srgb')
    parser.add_argument('--exposure-scale',type=float,default=1)
    args=parser.parse_args()
    try:report=fit(args)
    except (OSError,ValueError) as error:parser.exit(1,str(error)+'\n')
    print(json.dumps(dict(output=str(args.out),package_sha256=report['package_sha256'],samples=report['samples']),indent=2))


if __name__=='__main__':main()
