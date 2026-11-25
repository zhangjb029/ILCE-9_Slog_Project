"""Strict CUBE reader and explicit colour encodings for offline A9 fitting."""
import shlex
import numpy as np

class Cube:
    def __init__(self,table,lo,hi,title='',comments=()):
        self.table=table;self.lo=lo;self.hi=hi;self.title=title;self.comments=comments
    @classmethod
    def parse(cls,text):
        headers={};rows=[];comments=[]
        for line in text.lstrip('\ufeff').splitlines():
            if line.strip().startswith('#'):comments.append(line.strip()[1:].strip())
            stripped=line.strip()
            bits=stripped.split('#',1)[0].split()if stripped and stripped[0]in'0123456789+-.nNiI'else shlex.split(line,comments=True)
            if not bits:continue
            key=bits[0]
            if key in ('TITLE','LUT_3D_SIZE','LUT_1D_SIZE','DOMAIN_MIN','DOMAIN_MAX','LUT_3D_INPUT_RANGE','LUT_1D_INPUT_RANGE'):
                if key in headers:raise ValueError('duplicate '+key)
                headers[key]=bits[1:];continue
            try:
                if len(bits)!=3:raise ValueError('expected three data columns')
                rows.append([float(x)for x in bits])
            except ValueError as e:raise ValueError('unsupported directive or bad data: '+line[:100])from e
        if 'LUT_1D_SIZE'in headers and 'LUT_3D_SIZE'in headers:raise ValueError('combined 1D+3D shaper not supported; do not ignore it')
        dim=3 if 'LUT_3D_SIZE'in headers else 1
        try:
            n=int(headers[f'LUT_{dim}D_SIZE'][0]);lo=np.array(headers.get('DOMAIN_MIN',['0']*3),float);hi=np.array(headers.get('DOMAIN_MAX',['1']*3),float)
            range_key=f'LUT_{dim}D_INPUT_RANGE'
            if range_key in headers:
                if 'DOMAIN_MIN'in headers or 'DOMAIN_MAX'in headers:raise ValueError('ambiguous range')
                a,b=map(float,headers[range_key]);lo=np.full(3,a);hi=np.full(3,b)
        except(KeyError,IndexError,TypeError)as e:raise ValueError('missing or invalid dimensions')from e
        data=np.array(rows,float)
        if not 2<=n<=129 or data.shape!=(n**dim,3)or lo.shape!=(3,)or hi.shape!=(3,)or not np.isfinite(data).all()or not np.isfinite(lo).all()or not np.isfinite(hi).all()or np.any(hi<=lo):raise ValueError('invalid CUBE dimensions, domain or samples')
        table=data.reshape((n,n,n,3))if dim==3 else data
        return cls(table,lo,hi,' '.join(headers.get('TITLE',[])),comments)
    def __call__(self,rgb):
        x=np.asarray(rgb,float)
        if x.ndim!=2 or x.shape[1]!=3 or not np.isfinite(x).all():raise ValueError('expected finite (N,3)')
        n=len(self.table);u=np.clip((x-self.lo)/(self.hi-self.lo),0,1)*(n-1)
        if self.table.ndim==2:return np.stack([np.interp(u[:,c],np.arange(n),self.table[:,c])for c in range(3)],axis=1)
        low=np.minimum(np.floor(u).astype(int),n-2);f=u-low;out=np.zeros_like(x)
        for r in (0,1):
            for g in (0,1):
                for b in (0,1):
                    k=np.array([r,g,b]);at=low+k;weight=np.prod(np.where(k,f,1-f),axis=1)
                    out+=weight[:,None]*self.table[at[:,2],at[:,1],at[:,0]]
        return out

PRIMARIES={
 'srgb':[(.64,.33),(.30,.60),(.15,.06),(.3127,.3290)],
 'adobe':[(.64,.33),(.21,.71),(.15,.06),(.3127,.3290)],
 'rec2020':[(.708,.292),(.170,.797),(.131,.046),(.3127,.3290)],
 'fgamut':[(.708,.292),(.170,.797),(.131,.046),(.3127,.3290)],
 'vgamut':[(.730,.280),(.165,.840),(.100,-.030),(.3127,.3290)],
 'prophoto':[(.7347,.2653),(.1596,.8404),(.0366,.0001),(.3457,.3585)],
 'fgamutc':[(.7347,.2653),(.0263,.9737),(.1173,-.0224),(.3127,.3290)]}
def xyz_white(xy):x,y=xy;return np.array([x/y,1,(1-x-y)/y])
def matrix(space):
    p=PRIMARIES[space];m=np.stack([xyz_white(xy)for xy in p[:3]],axis=1)
    return m@np.diag(np.linalg.solve(m,xyz_white(p[3])))
def adaptation(source,dest):
    b=np.array([[.8951,.2664,-.1614],[-.7502,1.7135,.0367],[.0389,-.0685,1.0296]])
    return np.linalg.inv(b)@np.diag((b@xyz_white(PRIMARIES[dest][3]))/(b@xyz_white(PRIMARIES[source][3])))@b
def convert_rgb(linear,source,dest):
    if source==dest:return np.asarray(linear,float).copy()
    m=np.linalg.inv(matrix(dest))@adaptation(source,dest)@matrix(source)
    return np.asarray(linear,float)@m.T
def decode(x,curve):
    x=np.asarray(x,float)
    if curve=='srgb':return np.where(x<=.04045,x/12.92,((np.maximum(x,0)+.055)/1.055)**2.4)
    if curve=='linear':return x
    gamma={'adobe':563/256,'gamma22':2.2,'gamma24':2.4,'prophoto':1.8}[curve]
    return np.sign(x)*np.abs(x)**gamma
def encode(x,curve):
    x=np.asarray(x,float)
    if curve=='srgb':return np.where(x<=.0031308,x*12.92,1.055*np.maximum(x,0)**(1/2.4)-.055)
    if curve=='linear':return x
    gamma={'adobe':563/256,'gamma22':2.2,'gamma24':2.4,'prophoto':1.8}[curve]
    return np.sign(x)*np.abs(x)**(1/gamma)
def log_encode(x,curve):
    x=np.maximum(np.asarray(x,float),0)
    if curve=='vlog':return np.where(x<.01,5.6*x+.125,.241514*np.log10(x+.00873)+.598206)
    if curve=='flog':return np.where(x<.00089,8.735631*x+.092864,.344676*np.log10(.555556*x+.009468)+.790453)
    if curve=='flog2':return np.where(x<.000889,8.799461*x+.092864,.245281*np.log10(5.555556*x+.064829)+.384316)
    if curve=='nlog':return np.where(x<.328,650*np.cbrt(x+.0075),150*np.log(np.maximum(x,1e-20))+619)/1023
    raise ValueError('unknown log curve '+curve)
def reference(cube,rgb,mode,spec):
    """rgb uses A9's nominal output encoding; no camera response equivalence claim."""
    space,curve=('srgb','srgb')if mode==0 else('adobe','adobe')
    linear=decode(np.asarray(rgb)/255,curve)
    q=convert_rgb(linear,space,spec['input_gamut'])*spec.get('exposure_scale',1)
    c=spec['input_curve'];q=log_encode(q,c)if c in('vlog','flog','flog2','nlog')else encode(q,c)
    out=cube(q)
    out=convert_rgb(decode(out,spec['output_curve']),spec['output_gamut'],space)
    return np.clip(encode(out,curve),0,1)*255
