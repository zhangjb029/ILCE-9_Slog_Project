"""Fit complete photo references to two bounded A9 source-property candidates."""
import io
import json
import hashlib
import runtime as rt
import numpy as np
import a9_model as a9
from color_delta import delta_e_2000


def statistics(reference,predicted,mode):
    reference=np.asarray(reference,dtype=float)
    predicted=np.asarray(predicted,dtype=float)
    if (reference.ndim!=2 or reference.shape[1:]!=(3,) or
        predicted.shape!=reference.shape or len(reference)==0 or
        not np.all(np.isfinite(reference)) or not np.all(np.isfinite(predicted))):
        raise ValueError('Metrics require matching, finite, nonempty (N,3) arrays')
    de=delta_e_2000(a9.lab(reference,mode),a9.lab(predicted,mode))
    return dict(samples=len(de),deltaE00_mean=float(de.mean()),deltaE00_median=float(np.median(de)),
                deltaE00_p95=float(np.quantile(de,.95)),deltaE00_max=float(de.max()),
                RGB_RMSE_255=float(np.sqrt(np.mean((reference-predicted)**2))))


def context(stock, baseline, expand):
    at,unanchored=a9.inverse_stock(stock,baseline,expand)
    w=a9.design(at); stock_coords=w@a9.node_outputs(stock)
    anchor=a9.compressed(baseline,expand)-stock_coords
    return at,w,anchor,dict(inverse_stock_RGB_RMSE_255=float(np.sqrt(np.mean((baseline-unanchored)**2))),
                            residual_anchor_applied=True)

