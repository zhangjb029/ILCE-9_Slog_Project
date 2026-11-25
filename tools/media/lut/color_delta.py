"""CIEDE2000 (kL=kC=kH=1), validated against Sharma/Wu/Dalal's 34 pairs.

Reference: https://hajim.rochester.edu/ece/sites/gsharma/ciede2000/
Inputs are CIELAB values with a common reference white, no normalization here.
"""
import numpy as np

def delta_e_2000(reference,sample):
    x,y=np.broadcast_arrays(np.asarray(reference,dtype=float),np.asarray(sample,dtype=float))
    L1,a1,b1=np.moveaxis(x,-1,0);L2,a2,b2=np.moveaxis(y,-1,0)
    C1=np.hypot(a1,b1);C2=np.hypot(a2,b2);C=(C1+C2)/2
    G=.5*(1-np.sqrt(C**7/(C**7+25**7)))
    ap1=(1+G)*a1;ap2=(1+G)*a2
    cp1=np.hypot(ap1,b1);cp2=np.hypot(ap2,b2);prod=cp1*cp2
    h1=np.mod(np.arctan2(b1,ap1),2*np.pi);h2=np.mod(np.arctan2(b2,ap2),2*np.pi)
    h1=np.where(cp1==0,0,h1);h2=np.where(cp2==0,0,h2)
    dl=L2-L1;dc=cp2-cp1;dh=h2-h1
    dh=np.where(dh>np.pi,dh-2*np.pi,dh);dh=np.where(dh<-np.pi,dh+2*np.pi,dh)
    dh=np.where(prod==0,0,dh);dH=2*np.sqrt(prod)*np.sin(dh/2)
    lp=(L1+L2)/2;cp=(cp1+cp2)/2;hp=(h1+h2)/2
    hp=np.where(abs(h1-h2)>np.pi,hp-np.pi,hp);hp=np.mod(hp,2*np.pi)
    hp=np.where(prod==0,h1+h2,hp)
    T=1-.17*np.cos(hp-np.pi/6)+.24*np.cos(2*hp)+.32*np.cos(3*hp+np.pi/30)-.20*np.cos(4*hp-63*np.pi/180)
    sl=1+.015*(lp-50)**2/np.sqrt(20+(lp-50)**2);sc=1+.045*cp;sh=1+.015*cp*T
    theta=(np.pi/6)*np.exp(-((np.degrees(hp)-275)/25)**2)
    rt=-2*np.sqrt(cp**7/(cp**7+25**7))*np.sin(2*theta)
    return np.sqrt(np.maximum((dl/sl)**2+(dc/sc)**2+(dH/sh)**2+rt*(dc/sc)*(dH/sh),0))
