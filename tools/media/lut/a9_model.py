"""Offline model of R9.1's experimental Y/compressed-chroma interpretation.

This is a fitting model, not an identified/bit-exact A9 ISP. Nothing here writes
properties or a device. Source properties remain signed8 storage of signed7.
"""
from itertools import product
import numpy as np
from scipy.sparse import coo_matrix, eye
from scipy.optimize import minimize

NODE_COORDS = np.stack(np.meshgrid(np.arange(5)*64, np.arange(9)*32-128,
                                  np.arange(9)*32-128, indexing='ij'), -1).reshape(405, 3)


def source_values(stock):
    if not isinstance(stock, bytes) or len(stock) != 1280:
        raise ValueError('Expected a 1280-byte source property')
    values = np.frombuffer(stock[:1215], dtype=np.int8).astype(float)
    if np.any((values < -64) | (values > 63)):
        raise ValueError('Invalid signed7 source property')
    return values


def limits(stock):
    original = source_values(stock).astype(int)
    maximum = np.repeat([24, 32, 32], 405)
    def valid(candidate):
        result = (candidate >= -64) & (candidate <= 63)
        for level in range(1, 9):
            a = (np.floor_divide(candidate*level, 8) if level < 8 else candidate) & 127
            b = (np.floor_divide(original*level, 8) if level < 8 else original) & 127
            a = np.where(a < 64, a, a-128)
            b = np.where(b < 64, b, b-128)
            result &= np.abs(a-b) <= maximum
        return result
    low = original.copy(); high = original.copy()
    for _ in range(127):
        low -= valid(low-1)
        high += valid(high+1)
    return low, high


def make_table(values, stock):
    source_values(stock)
    values = np.asarray(values, float)
    if values.size != 1215 or not np.isfinite(values).all():
        raise ValueError('Expected 1215 finite correction values')
    values = values.reshape(1215)
    low, high = limits(stock)
    rounded = np.where(values >= 0, np.floor(values+.5), -np.floor(-values+.5))
    result = np.clip(rounded, low, high).astype(int).reshape(3, 5, 9, 9)
    lo = np.clip(np.arange(5)[:, None, None]*64 + low[:405].reshape(5,9,9), 0, 256)
    hi = np.clip(np.arange(5)[:, None, None]*64 + high[:405].reshape(5,9,9), 0, 256)
    hi = np.minimum.accumulate(hi[::-1], axis=0)[::-1]
    if np.any(lo > hi):
        raise ValueError('No monotone table exists inside production bounds')
    previous = np.zeros((9,9), int)
    for a in range(5):
        y = np.maximum(previous, np.clip(a*64+result[0,a], lo[a], hi[a]))
        result[0,a] = y-a*64
        previous = y
    output = result.astype(np.int8).tobytes() + stock[1215:]
    check = source_values(output)
    if np.any((check < low) | (check > high)):
        raise ValueError('Monotonic projection exceeded production bounds')
    return output


def design(coords):
    """405-column trilinear interpolation, axis order exactly a*81+b*9+c."""
    coords = np.asarray(coords, float)
    u = np.clip((coords-[0,-128,-128])/[64,32,32], [0,0,0], [4,8,8])
    low = np.minimum(np.floor(u).astype(int), [3,7,7]); fraction = u-low
    rows=[]; columns=[]; values=[]
    for corner in product((0,1), repeat=3):
        c=np.asarray(corner); at=low+c
        rows.append(np.arange(len(u)))
        columns.append(at[:,0]*81+at[:,1]*9+at[:,2])
        values.append(np.prod(np.where(c, fraction, 1-fraction), axis=1))
    return coo_matrix((np.concatenate(values),(np.concatenate(rows),np.concatenate(columns))),
                      shape=(len(u),405)).tocsr()


def rgb_to_ycc(rgb):
    x = np.asarray(rgb, float)/255
    y = x @ np.array([.299,.587,.114])
    return np.stack([y*256,(x[:,2]-y)/(2*(1-.114))*1024,
                     (x[:,0]-y)/(2*(1-.299))*1024], axis=1)


def ycc_to_rgb(ycc):
    y,cb,cr = (np.asarray(ycc,float)/[256,1024,1024]).T
    r=y+2*(1-.299)*cr; b=y+2*(1-.114)*cb
    g=(y-.299*r-.114*b)/.587
    return np.stack([r,g,b],axis=1)*255


def decode_rgb(rgb, mode=0):
    x = np.asarray(rgb, float)/255
    if mode == 1:
        return np.sign(x)*np.abs(x)**(563/256)
    if mode != 0: raise ValueError('Unknown RGB domain')
    return np.where(x <= .04045, x/12.92, ((np.maximum(x,0)+.055)/1.055)**2.4)


def encode_rgb(linear, mode=0):
    x = np.asarray(linear,float)
    if mode == 1:
        return np.sign(x)*np.abs(x)**(256/563)*255
    if mode != 0: raise ValueError('Unknown RGB domain')
    return np.where(x <= .0031308, x*12.92, 1.055*np.maximum(x,0)**(1/2.4)-.055)*255


def to_xyz(rgb, mode=0):
    matrix = np.array([[.4124564,.3575761,.1804375],[.2126729,.7151522,.0721750],
                       [.0193339,.1191920,.9503041]]) if mode == 0 else np.array(
                      [[.5767309,.1855540,.1881852],[.2973769,.6273491,.0752741],
                       [.0270343,.0706872,.9911085]])
    return decode_rgb(np.clip(rgb,0,255),mode) @ matrix.T


def lab(rgb, mode=0):
    xyz=to_xyz(rgb,mode)/[.95047,1,1.08883]
    f=np.where(xyz>(6/29)**3,np.cbrt(xyz),xyz/(3*(6/29)**2)+4/29)
    return np.stack([116*f[:,1]-16,500*(f[:,0]-f[:,1]),200*(f[:,1]-f[:,2])],axis=1)


def compressed(rgb, expand):
    ycc=rgb_to_ycc(rgb)
    out=ycc.copy()
    for c in (1,2):
        out[:,c]=np.sign(ycc[:,c])*np.interp(np.abs(ycc[:,c]),expand,np.arange(129))
    return out


def decode_compressed(coords, expand):
    ycc=np.asarray(coords,float).copy()
    for c in (1,2):
        ycc[:,c]=np.sign(ycc[:,c])*np.interp(np.abs(ycc[:,c]),np.arange(129),expand)
    return np.clip(ycc_to_rgb(ycc),0,255)


def node_outputs(table):
    values=source_values(table).reshape(3,405).T
    result=NODE_COORDS.copy().astype(float)
    result[:,0]=np.clip(result[:,0]+values[:,0],0,256)
    result[:,1:]=np.clip(result[:,1:]+np.floor(values[:,1:]*3/4),-128,128)
    return result


def evaluate(table, coords, expand):
    return decode_compressed(design(coords) @ node_outputs(table),expand)


def inverse_stock(stock, baseline_rgb, expand):
    wanted=compressed(baseline_rgb,expand)
    at=wanted.copy(); nodes=node_outputs(stock)
    for _ in range(48):
        delta=wanted-design(at)@nodes
        at=np.clip(at+.7*delta,[0,-128,-128],[256,128,128])
    predicted=decode_compressed(design(at)@nodes,expand)
    return at, predicted


def fit(coords, target_rgb, stock, expand, desired_coords=None):
    """Bounded least squares in decoded Y/compressed-chroma coordinates.

    Equal-weight point errors plus small stock/smoothness regularization.
    No data-driven claim about camera hardware is made by this optimizer.
    """
    w=design(coords)
    target=compressed(target_rgb,expand) if desired_coords is None else np.asarray(desired_coords,float)
    low,high=limits(stock); original=source_values(stock).reshape(3,405).T
    gram=(w.T@w).toarray()/len(coords)
    # Smooth *change* from stock, preserving factory structure in sparse regions.
    edge=[]
    for a,b,c in product(range(5),range(9),range(9)):
        i=a*81+b*9+c
        for d,ok in ((81,a<4),(9,b<8),(1,c<8)):
            if ok: edge.append((i,i+d))
    smooth=np.zeros((405,405))
    for i,j in edge:
        smooth[i,i]+=1;smooth[j,j]+=1;smooth[i,j]-=1;smooth[j,i]-=1
    regular=2e-5*np.eye(405)+2e-5*smooth
    matrix=gram+regular
    sources=[]; unconstrained=[]; optimization=[]
    for channel in range(3):
        scale=1 if channel==0 else .75
        offset=np.asarray(w@NODE_COORDS[:,channel]).ravel()
        rhs=np.asarray(w.T@((target[:,channel]-offset)/scale)).ravel()/len(coords)+regular@original[:,channel]
        free=np.linalg.solve(matrix,rhs)
        lo=low.reshape(3,405)[channel];hi=high.reshape(3,405)[channel]
        def loss(x):
            grad=matrix@x-rhs
            return float(.5*x@(matrix@x)-rhs@x),grad
        result=minimize(loss,np.clip(free,lo,hi),jac=True,method='L-BFGS-B',bounds=list(zip(lo,hi)),
                        options={'maxiter':400,'ftol':1e-13,'gtol':1e-8,'maxcor':20})
        if not np.isfinite(result.x).all(): raise ValueError('Nonfinite optimization')
        sources.append(result.x);unconstrained.append(free)
        optimization.append(dict(success=bool(result.success),message=str(result.message),iterations=int(result.nit)))
    values=np.stack(sources).ravel(); output=make_table(values,stock)
    actual=source_values(output)
    return output,dict(optimization=optimization,boundary_nodes=int(np.count_nonzero((actual==low)|(actual==high))),
                       rounding_rmse_codes=float(np.sqrt(np.mean((actual-values)**2))),
                       free_outside_bounds=int(np.count_nonzero((np.stack(unconstrained).ravel()<low)|
                                                                (np.stack(unconstrained).ravel()>high)))),np.stack(unconstrained)
