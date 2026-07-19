import time, tkinter as tk
import app, layout, ddc, profiles, theme, vcp_inputs
app.messagebox.showinfo = lambda *a, **k: None
app.messagebox.showwarning = lambda *a, **k: None
app.tray_mod.Tray.start = lambda self: False
layout.get_displays = lambda *a,**k: []
sim=[ddc.Monitor(0,r"\\.\DISPLAY2\Monitor0","37","S37","A37","MONITOR\\A37"),
     ddc.Monitor(1,r"\\.\DISPLAY3\Monitor0","27","S27","A27","MONITOR\\A27")]
ddc.list_monitors=lambda: sim
ddc.get_input_source=lambda m:0x0F
ddc.set_input_source=lambda m,v:None
ws=profiles.Workspace("Work",[profiles.Assignment("S37","37",0x11,"HDMI 1"),
                              profiles.Assignment("S27","27",0x11,"HDMI 1")])
app.profiles.load=lambda: profiles.Store(workspaces=[ws])
theme.THEME.name="dark"; theme.THEME.accent="#025500"; theme.THEME._recompute()

a=app.App()
for _ in range(15): a.update_idletasks(); a.update(); time.sleep(0.02)
sw=app.SetupWindow(a)
# switch to Workspaces tab context: select the ws
sw.ws_list.selection_set(0); sw._show_ws_detail()
a.update_idletasks(); a.update()
print("exportselection:", sw.ws_list.cget("exportselection"))
print("editors present before:", len(sw._editors))
print("detail children before:", len(sw.detail.winfo_children()))

# Simulate what broke it: set a combo to 'Leave unchanged' (combo grabs selection),
# then fire the listbox's <<ListboxSelect>> handler as Tk would.
combo0 = None
def find_combo(w):
    global combo0
    for c in w.winfo_children():
        if c.winfo_class()=="TCombobox" and combo0 is None: combo0=c
        find_combo(c)
find_combo(sw.detail)
combo0.set(vcp_inputs.SKIP_LABEL)
a.update_idletasks(); a.update()
# emulate the stray ListboxSelect event that previously wiped the pane
sw._show_ws_detail()
a.update_idletasks(); a.update()
print("detail children after Leave-unchanged + reselect:", len(sw.detail.winfo_children()))
sel = sw.ws_list.curselection()
print("listbox still has selection:", sel)
vals=[gv() for (_,gv) in sw._editors]
print("editor values:", [hex(v) if v is not None and v>=0 else v for v in vals])
assert len(sw.detail.winfo_children())>0, "pane must NOT be wiped"
assert sel, "listbox selection must be retained"
print("PASS: pane intact, selection retained")
# do NOT call _quit_app (it os._exit's). Just destroy.
sw.destroy(); a.destroy()
print("ALL OK")
