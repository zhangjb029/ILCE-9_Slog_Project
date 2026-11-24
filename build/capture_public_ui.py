"""Create anonymous UI illustrations without opening any camera connection."""
import ctypes
from pathlib import Path
import sys
import tkinter as tk
from unittest.mock import patch
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from a9tool import gui, journal


def capture(root,path):
    root.update()
    user,gdi=ctypes.windll.user32,ctypes.windll.gdi32
    hwnd=root.winfo_id()
    width,height=root.winfo_width(),root.winfo_height()
    dc=user.GetDC(hwnd); memory=gdi.CreateCompatibleDC(dc)
    bitmap=gdi.CreateCompatibleBitmap(dc,width,height);previous=gdi.SelectObject(memory,bitmap)
    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_=[('size',ctypes.c_uint32),('width',ctypes.c_int32),('height',ctypes.c_int32),
                  ('planes',ctypes.c_uint16),('bits',ctypes.c_uint16),('compression',ctypes.c_uint32),
                  ('image_size',ctypes.c_uint32),('x',ctypes.c_int32),('y',ctypes.c_int32),
                  ('used',ctypes.c_uint32),('important',ctypes.c_uint32)]
    try:
        if not user.PrintWindow(hwnd,memory,3):raise RuntimeError('PrintWindow failed')
        header=BITMAPINFOHEADER(40,width,-height,1,32,0,0,0,0,0,0)
        buffer=ctypes.create_string_buffer(width*height*4)
        if not gdi.GetDIBits(memory,bitmap,0,height,buffer,ctypes.byref(header),0):
            raise RuntimeError('GetDIBits failed')
        Image.frombytes('RGB',(width,height),buffer.raw,'raw','BGRX').save(path)
    finally:
        gdi.SelectObject(memory,previous);gdi.DeleteObject(bitmap);gdi.DeleteDC(memory);user.ReleaseDC(hwnd,dc)


if __name__=='__main__':
    out=ROOT/'docs/release-v190-ui';out.mkdir(exist_ok=True)
    with patch.object(journal,'sessions_root',return_value=Path('C:/A9Tool/sessions')):
        root=tk.Tk();app=gui.App(root);root.geometry('960x780+0+0')
        root.update()
        for i,name in enumerate(('fn','flash','r15nh','v8','wifi','reset')):
            app.notebook.select(i);root.update()
            capture(root,out/f'{i+1:02d}-{name}.png')
        root.destroy()
    print('Six anonymous UI illustrations written; no camera accessed')
