"""Perceptual refinement; validation chooses candidates, test rows never fit."""
import json
import runtime as rt
import numpy as np
import torch
import a9_model as a9
from fit_metrics import context,statistics

torch.set_num_threads(1)


def torch_lab(rgb,mode):
    x=rgb.clamp(0,255)/255
    linear=x**(563/256)if mode else torch.where(x<=.04045,x/12.92,((x+.055)/1.055)**2.4)
    matrix=torch.tensor([[.4124564,.3575761,.1804375],[.2126729,.7151522,.0721750],[.0193339,.1191920,.9503041]]
             if mode==0 else [[.5767309,.1855540,.1881852],[.2973769,.6273491,.0752741],[.0270343,.0706872,.9911085]],dtype=x.dtype)
    v=(linear@matrix.T)/torch.tensor([.95047,1,1.08883],dtype=x.dtype)
    f=torch.where(v>(6/29)**3,v.clamp_min(1e-9)**(1/3),v/(3*(6/29)**2)+4/29)
    return torch.stack([116*f[:,1]-16,500*(f[:,0]-f[:,1]),200*(f[:,1]-f[:,2])],1)


def de00_squared(x,y):
    L1,a1,b1=x.unbind(1);L2,a2,b2=y.unbind(1)
    C1=(a1*a1+b1*b1+1e-12).sqrt();C2=(a2*a2+b2*b2+1e-12).sqrt();C=(C1+C2)/2
    G=.5*(1-(C**7/(C**7+25**7)).clamp_min(1e-20).sqrt())
    ap1=(1+G)*a1;ap2=(1+G)*a2
    cp1=(ap1*ap1+b1*b1+1e-12).sqrt();cp2=(ap2*ap2+b2*b2+1e-12).sqrt();prod=cp1*cp2
    h1=torch.remainder(torch.atan2(b1+1e-9,ap1+1e-9),2*np.pi)
    h2=torch.remainder(torch.atan2(b2+1e-9,ap2+1e-9),2*np.pi)
    dl=L2-L1;dc=cp2-cp1;dh=h2-h1
    dh=torch.where(dh>np.pi,dh-2*np.pi,dh);dh=torch.where(dh<-np.pi,dh+2*np.pi,dh)
    dH=2*prod.clamp_min(1e-12).sqrt()*torch.sin(dh/2)
    lp=(L1+L2)/2;cp=(cp1+cp2)/2;hp=(h1+h2)/2
    hp=torch.where((h1-h2).abs()>np.pi,hp-np.pi,hp);hp=torch.remainder(hp,2*np.pi)
    T=1-.17*torch.cos(hp-np.pi/6)+.24*torch.cos(2*hp)+.32*torch.cos(3*hp+np.pi/30)-.20*torch.cos(4*hp-63*np.pi/180)
    sl=1+.015*(lp-50)**2/(20+(lp-50)**2).sqrt();sc=1+.045*cp;sh=1+.015*cp*T
    theta=(np.pi/6)*torch.exp(-((hp*180/np.pi-275)/25)**2)
    rt_term=-2*(cp**7/(cp**7+25**7)).clamp_min(1e-20).sqrt()*torch.sin(2*theta)
    return ((dl/sl)**2+(dc/sc)**2+(dH/sh)**2+rt_term*(dc/sc)*(dH/sh)).clamp_min(0)


def refine_table(initial,stock,coords,anchor,target,expand,mode,steps=240,validation=None):
    w=a9.design(coords); counts=np.diff(w.indptr)
    if not np.all(counts==8):raise ValueError('Expected eight interpolation corners')
    idx=torch.tensor(w.indices.reshape(-1,8),dtype=torch.int64)
    weights=torch.tensor(w.data.reshape(-1,8),dtype=torch.float32)
    origin=torch.tensor(a9.NODE_COORDS,dtype=torch.float32)
    anch=torch.tensor(anchor,dtype=torch.float32)
    expansion=torch.tensor(expand,dtype=torch.float32)
    target_lab=torch.tensor(a9.lab(target,mode),dtype=torch.float32)
    p=torch.nn.Parameter(torch.tensor(a9.source_values(initial).reshape(3,405).T,dtype=torch.float32))
    low,high=a9.limits(stock)
    lower=torch.tensor(low.reshape(3,405).T,dtype=torch.float32);upper=torch.tensor(high.reshape(3,405).T,dtype=torch.float32)
    optimizer=torch.optim.Adam([p],lr=.55)
    def predict():
        scaled=p[:,1:]*.75
        # Exact floor forward, straight-through derivative used only to search.
        chroma=scaled+(torch.floor(scaled)-scaled).detach()
        nodes=torch.cat([(origin[:,:1]+p[:,:1]).clamp(0,256),
                          (origin[:,1:]+chroma).clamp(-128,128)],1)
        q=(nodes[idx]*weights[:,:,None]).sum(1)+anch
        u=q[:,1:].clamp(-128,128)
        absolute=torch.where(u<0,-u,u)
        k=absolute.floor().long().clamp(0,127);fraction=absolute-k
        expanded=expansion[k]*(1-fraction)+expansion[k+1]*fraction
        cbcr=torch.where(u<0,-expanded,expanded)/1024
        y=q[:,0]/256;cb,cr=cbcr.unbind(1)
        r=y+1.402*cr;b=y+1.772*cb;g=(y-.299*r-.114*b)/.587
        return torch.stack([r,g,b],1).mul(255).clamp(0,255)
    def score(raw):
        if validation is None:
            predicted=a9.decode_compressed(a9.design(coords)@a9.node_outputs(raw)+anchor,expand)
            s=statistics(target,predicted,mode)
        else:
            at,wv,av,tv=validation
            predicted=a9.decode_compressed(wv@a9.node_outputs(raw)+av,expand)
            s=statistics(tv,predicted,mode)
        return s['deltaE00_mean']+.1*s['deltaE00_p95'],s
    best=initial;best_score,best_metrics=score(initial);initial_score=best_score
    history=[];nonfinite=False
    for step in range(steps):
        optimizer.zero_grad()
        squared=de00_squared(target_lab,torch_lab(predict(),mode))
        # Smooth approximation to mean DE00, with a modest tail penalty.
        loss=(squared+1e-4).sqrt().mean()+.004*squared.mean()
        loss.backward()
        if not torch.isfinite(loss)or p.grad is None or not torch.isfinite(p.grad).all():
            nonfinite=True;break
        torch.nn.utils.clip_grad_norm_([p],5)
        optimizer.step()
        with torch.no_grad():p.clamp_(lower,upper)
        if(step+1)%40==0 or step+1==steps:
            candidate=a9.make_table(p.detach().numpy().T.ravel(),stock)
            value,metrics=score(candidate)
            history.append(dict(step=step+1,training_loss=float(loss.detach()),validation_score=value))
            if value<best_score:
                best=candidate;best_score=value;best_metrics=metrics
    return best,dict(steps_requested=steps,nonfinite_search_stopped=nonfinite,
                     initial_validation_score=initial_score,selected_validation_score=best_score,
                     selected_validation=best_metrics,history=history,
                     held_out_test_used_for_selection=False)

