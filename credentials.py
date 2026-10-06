"""Windows user-bound credential encryption; never prints secrets."""
import ctypes,json,os
from ctypes import wintypes
from pathlib import Path
FILE=Path(__file__).resolve().parent/'data'/'credentials.dpapi'
class Blob(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_char))]
def crypt(data,decrypt=False):
    buf=ctypes.create_string_buffer(data)
    source=Blob(len(data),ctypes.cast(buf,ctypes.POINTER(ctypes.c_char)))
    output=Blob()
    api=ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not api(ctypes.byref(source),None,None,None,None,1,ctypes.byref(output)):
        raise ctypes.WinError()
    try:return ctypes.string_at(output.data,output.size)
    finally:ctypes.windll.kernel32.LocalFree(output.data)
def load():
    if os.name=='nt' and FILE.exists():
        for k,v in json.loads(crypt(FILE.read_bytes(),True)).items():os.environ[k]=v
if __name__=='__main__':
    import tkinter as tk
    from tkinter import messagebox
    root=tk.Tk();root.title('Jev Lab — claves privadas');root.geometry('560x380')
    tk.Label(root,text='Configurar Jev y Alpaca PAPER',font=('Segoe UI',16)).pack(pady=15)
    tk.Label(root,text='Introduce las claves aquí. No se envían al chat.\nAlpaca requiere API Key y Secret Key de PAPER.',justify='left').pack()
    entries={}
    for label,key in [('Jev API Key','TYPESAFE_API_KEY'),('Alpaca PAPER API Key','ALPACA_PAPER_API_KEY'),('Alpaca PAPER Secret Key','ALPACA_PAPER_SECRET_KEY')]:
        tk.Label(root,text=label).pack(anchor='w',padx=25,pady=(8,0))
        entry=tk.Entry(root,show='*',width=65);entry.pack(padx=25);entries[key]=entry
    def save():
        values={k:e.get().strip() for k,e in entries.items()}
        if not all(values.values()):return messagebox.showerror('Faltan claves','Completa los tres campos.')
        FILE.parent.mkdir(exist_ok=True)
        FILE.write_bytes(crypt(json.dumps(values).encode()))
        for e in entries.values():e.delete(0,'end')
        messagebox.showinfo('Guardado','Claves cifradas para tu usuario de Windows.\nAvísame para verificar las conexiones. No se enviaron órdenes.')
        root.destroy()
    tk.Button(root,text='Guardar claves localmente',command=save).pack(pady=18)
    root.mainloop()
