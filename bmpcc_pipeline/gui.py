"""Easy-to-use Tkinter front-end for the BMPCC OG firmware patcher."""

import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .patcher import CameraSetup, build_patched, inspect
from .patches import PATCHES

APP_TITLE = "BMPCC OG Firmware Patcher"
DISCLAIMER = (
    "Experimental homebrew tool. Modified firmware can brick the camera. "
    "Use a spare body and keep the stock image + backups. Not affiliated with "
    "Blackmagic Design."
)


def _is_writable_dir(path):
    try:
        probe = os.path.join(path, ".bmpcc_write_test")
        with open(probe, "w"):
            pass
        os.remove(probe)
        return True
    except OSError:
        return False


def find_camerasetup(preferred_dir=None):
    cands = []
    if preferred_dir:
        cands.append(os.path.join(preferred_dir, "CameraSetup.exe"))
    cands += [
        r"C:\Program Files\Blackmagic Design\Blackmagic Camera Setup\CameraSetup.exe",
        r"C:\Program Files (x86)\Blackmagic Design\Blackmagic Camera Setup\CameraSetup.exe",
    ]
    for root in (os.path.dirname(sys.executable), os.getcwd()):
        cands.append(os.path.join(root, "CameraSetup.exe"))
    return next((c for c in cands if os.path.isfile(c)), "")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("860x780")
        self.minsize(760, 680)
        self.q = queue.Queue()

        self.stock_var = tk.StringVar()
        self.out_var = tk.StringVar()
        self.cs_var = tk.StringVar()
        self.patch_var = tk.StringVar(value="version-bump")
        self.patch_label = tk.StringVar()
        self.version_var = tk.StringVar(value="2.2")
        self.force_var = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Ready")

        self._build_ui()
        self._on_patch_change()
        self.after(100, self._poll)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        ttk.Label(root, text=APP_TITLE,
                  font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(root, text="Patch and flash BlamOS on the original Pocket "
                            "Cinema Camera (PID bd73).",
                  foreground="#444").pack(anchor="w", pady=(0, 8))

        warn = tk.Label(root, text=DISCLAIMER, bg="#fff4ce", fg="#6b4e00",
                        justify="left", anchor="w", padx=10, pady=6,
                        font=("Segoe UI", 9))
        warn.pack(fill="x", pady=(0, 10))

        # 1 stock
        lf = ttk.LabelFrame(root, text="1. Stock firmware (data-bd73.bin)")
        lf.pack(fill="x", pady=4)
        row = ttk.Frame(lf)
        row.pack(fill="x", padx=8, pady=8)
        ttk.Entry(row, textvariable=self.stock_var).pack(
            side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse…", command=self._browse_stock).pack(
            side="left", padx=(8, 0))
        ttk.Label(lf, text="Extract this from the official Blackmagic Camera "
                           "Setup 2.8.1 installer. Do not redistribute it.",
                  foreground="#666", font=("Segoe UI", 8)).pack(
            anchor="w", padx=10, pady=(0, 6))

        # 2 patch
        lf = ttk.LabelFrame(root, text="2. Patch")
        lf.pack(fill="x", pady=4)
        row = ttk.Frame(lf)
        row.pack(fill="x", padx=8, pady=8)
        ttk.Label(row, text="Choose:").pack(side="left")
        self.patch_box = ttk.Combobox(
            row, state="readonly", width=38,
            values=[f"{p.name}" for p in PATCHES.values()])
        self.patch_box.current(0)
        self.patch_box.bind("<<ComboboxSelected>>", self._on_patch_change)
        self.patch_box.pack(side="left", padx=8)
        self.version_lbl = ttk.Label(row, text="New version:")
        self.version_lbl.pack(side="left", padx=(12, 4))
        self.version_entry = ttk.Entry(row, textvariable=self.version_var, width=6)
        self.version_entry.pack(side="left")
        ttk.Label(lf, textvariable=self.patch_label, foreground="#555",
                  wraplength=780, justify="left").pack(
            anchor="w", padx=10, pady=(0, 8))

        # 3 output
        lf = ttk.LabelFrame(root, text="3. Output image")
        lf.pack(fill="x", pady=4)
        row = ttk.Frame(lf)
        row.pack(fill="x", padx=8, pady=8)
        ttk.Entry(row, textvariable=self.out_var).pack(
            side="left", fill="x", expand=True)
        ttk.Button(row, text="Save as…", command=self._browse_out).pack(
            side="left", padx=(8, 0))

        # 4 build
        lf = ttk.LabelFrame(root, text="4. Build and verify")
        lf.pack(fill="x", pady=4)
        row = ttk.Frame(lf)
        row.pack(fill="x", padx=8, pady=8)
        ttk.Button(row, text="Build patched image",
                   command=self._build).pack(side="left")
        ttk.Button(row, text="Verify image",
                   command=self._verify).pack(side="left", padx=8)

        # 5 flash
        lf = ttk.LabelFrame(root, text="5. Flash with the official updater")
        lf.pack(fill="x", pady=4)
        row = ttk.Frame(lf)
        row.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Label(row, text="CameraSetup.exe:").pack(side="left")
        ttk.Entry(row, textvariable=self.cs_var).pack(
            side="left", fill="x", expand=True, padx=8)
        ttk.Button(row, text="Browse…", command=self._browse_cs).pack(
            side="left")
        ttk.Button(row, text="Detect", command=self._detect_cs).pack(
            side="left", padx=(8, 0))
        ttk.Checkbutton(
            lf, text="Allow re-flashing the same version (patches CameraSetup.exe, "
                     "keeps a .stock.exe backup)",
            variable=self.force_var).pack(anchor="w", padx=10, pady=(6, 0))
        row = ttk.Frame(lf)
        row.pack(fill="x", padx=8, pady=8)
        ttk.Button(row, text="Stage && launch updater",
                   command=self._stage).pack(side="left")
        ttk.Button(row, text="Restore stock data-bd73.bin",
                   command=self._restore_fw).pack(side="left", padx=8)
        ttk.Button(row, text="Restore CameraSetup.exe",
                   command=self._restore_cs).pack(side="left")

        # log
        lf = ttk.LabelFrame(root, text="Log")
        lf.pack(fill="both", expand=True, pady=4)
        self.log = tk.Text(lf, height=10, wrap="word", state="disabled",
                           font=("Consolas", 9))
        sb = ttk.Scrollbar(lf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        sb.pack(side="right", fill="y", padx=(0, 8), pady=8)

        ttk.Label(self, textvariable=self.status, anchor="w",
                  relief="sunken").pack(fill="x", side="bottom")

    # ------------------------------------------------------------- helpers
    def _current_patch(self):
        return list(PATCHES.values())[self.patch_box.current()]

    def _on_patch_change(self, _e=None):
        p = self._current_patch()
        self.patch_label.set(p.description)
        bump = p.key == "version-bump"
        state = "normal" if bump else "disabled"
        self.version_entry.configure(state=state)
        self.version_lbl.configure(foreground="#000" if bump else "#999")

    def _browse_stock(self):
        p = filedialog.askopenfilename(
            title="Select stock data-bd73.bin",
            filetypes=[("Firmware image", "*.bin"), ("All files", "*.*")])
        if not p:
            return
        self.stock_var.set(p)
        if not self.out_var.get():
            self.out_var.set(os.path.splitext(p)[0] + "-patched.bin")
        sibling = os.path.join(os.path.dirname(os.path.abspath(p)),
                               "CameraSetup.exe")
        if os.path.isfile(sibling):
            self.cs_var.set(sibling)
        if not self.cs_var.get():
            self._detect_cs()

    def _browse_out(self):
        p = filedialog.asksaveasfilename(
            title="Save patched image as", defaultextension=".bin",
            filetypes=[("Firmware image", "*.bin")],
            initialfile="data-bd73-patched.bin")
        if p:
            self.out_var.set(p)

    def _browse_cs(self):
        p = filedialog.askopenfilename(
            title="Select CameraSetup.exe",
            filetypes=[("CameraSetup", "CameraSetup.exe"), ("All files", "*.*")])
        if p:
            self.cs_var.set(p)

    def _detect_cs(self):
        found = find_camerasetup(
            os.path.dirname(self.stock_var.get()) if self.stock_var.get() else None)
        if found:
            self.cs_var.set(found)
            self._log(f"Detected updater: {found}")
        else:
            messagebox.showwarning(
                "Not found", "Could not find CameraSetup.exe.\n"
                "Browse to the installed or extracted Blackmagic Camera Setup.")

    def _log(self, msg):
        self.q.put(("log", msg))

    def _set_status(self, s):
        self.q.put(("status", s))

    def _poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.log.configure(state="normal")
                    self.log.insert("end", val + "\n")
                    self.log.see("end")
                    self.log.configure(state="disabled")
                elif kind == "status":
                    self.status.set(val)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _worker(self, fn):
        def run():
            try:
                fn()
            except Exception as e:  # noqa: BLE001 - shown in the UI
                self._log(f"ERROR: {e}")
                self._set_status("Failed")
        threading.Thread(target=run, daemon=True).start()

    # ------------------------------------------------------------- actions
    def _build(self):
        stock = self.stock_var.get().strip()
        out = self.out_var.get().strip()
        if not os.path.isfile(stock):
            messagebox.showerror("Missing input", "Select the stock data-bd73.bin first.")
            return
        if not out:
            out = os.path.splitext(stock)[0] + "-patched.bin"
            self.out_var.set(out)
        patch = self._current_patch()
        kwargs = {}
        if patch.key == "version-bump":
            kwargs["version"] = self.version_var.get().strip()
        self._set_status("Building…")
        self._log(f"Building: {patch.name}")

        def work():
            data = open(stock, "rb").read()
            rebuilt = build_patched(data, patch, **kwargs)
            open(out, "wb").write(rebuilt)
            info = inspect(rebuilt)
            self._log(f"  wrote {out} ({len(rebuilt)} bytes)")
            self._log(f"  version={info['version']}  digest_ok={info['digest_ok']}  "
                      f"sections_ok={info['sections_ok']}")
            self._set_status("Built and verified")
        self._log("  (this can take a few seconds)")
        self._worker(work)

    def _verify(self):
        path = self.out_var.get().strip()
        if not os.path.isfile(path):
            messagebox.showerror("Missing image", "Build or select an image first.")
            return
        self._set_status("Verifying…")

        def work():
            info = inspect(open(path, "rb").read())
            for k, v in info.items():
                self._log(f"  {k}: {v}")
            if not (info["digest_ok"] and info["sections_ok"]):
                raise RuntimeError("integrity verification failed")
            self._set_status("Image OK")
        self._worker(work)

    def _stage(self):
        cs = self.cs_var.get().strip()
        patched = self.out_var.get().strip()
        if not os.path.isfile(cs):
            messagebox.showerror("Missing updater", "Select CameraSetup.exe.")
            return
        if not os.path.isfile(patched):
            messagebox.showerror("Missing image", "Build the patched image first.")
            return
        d = os.path.dirname(os.path.abspath(cs))
        if not _is_writable_dir(d):
            messagebox.showerror(
                "Folder is not writable",
                f"{d}\n\nWindows will not let this tool write data-bd73.bin there.\n"
                "Run the patcher as administrator, or use an extracted (writable) "
                "copy of Camera Setup.")
            return
        info = inspect(open(patched, "rb").read())
        if not (info["digest_ok"] and info["sections_ok"]):
            messagebox.showerror("Refusing", "The patched image failed verification.")
            return
        if not messagebox.askyesno(
                "Flash modified firmware?",
                "This will:\n"
                "  • back up the current data-bd73.bin as data-bd73.stock.bin\n"
                "  • copy the patched image as data-bd73.bin\n"
                "  • optionally patch CameraSetup.exe so it will re-flash\n"
                "  • launch the official updater\n\n"
                "Use the spare camera. Continue?"):
            return
        self._set_status("Staging…")
        self._log("Staging patched image…")

        def work():
            target = os.path.join(d, "data-bd73.bin")
            backup = os.path.join(d, "data-bd73.stock.bin")
            if not os.path.exists(target):
                raise RuntimeError(f"{target} not found next to CameraSetup.exe")
            if not os.path.exists(backup):
                shutil.copy2(target, backup)
                self._log(f"  backed up stock -> {backup}")
            if self.force_var.get():
                res = CameraSetup.patch(cs)
                self._log(f"  CameraSetup force patch: {res}")
            shutil.copy2(patched, target)
            self._log(f"  staged {target}")
            subprocess.Popen([cs], cwd=d)
            self._log("  launched CameraSetup.exe")
            self._log("  Note: the updater may say 'failed' even when it worked; "
                      "verify by the camera's version/behaviour.")
            self._set_status("Updater launched")
        self._worker(work)

    def _restore_fw(self):
        cs = self.cs_var.get().strip()
        if not os.path.isfile(cs):
            messagebox.showerror("Missing updater", "Select CameraSetup.exe.")
            return
        d = os.path.dirname(os.path.abspath(cs))
        target = os.path.join(d, "data-bd73.bin")
        backup = os.path.join(d, "data-bd73.stock.bin")
        if not os.path.exists(backup):
            messagebox.showerror("No backup", f"No stock backup at\n{backup}")
            return
        if not messagebox.askyesno("Restore stock firmware?",
                                   f"Copy\n{backup}\nover\n{target}?"):
            return
        self._set_status("Restoring…")

        def work():
            shutil.copy2(backup, target)
            self._log(f"  restored {target}")
            self._set_status("Stock data-bd73.bin restored")
        self._worker(work)

    def _restore_cs(self):
        cs = self.cs_var.get().strip()
        if not os.path.isfile(cs):
            messagebox.showerror("Missing updater", "Select CameraSetup.exe.")
            return
        if not messagebox.askyesno("Restore CameraSetup.exe?",
                                   "Replace CameraSetup.exe with its stock backup?"):
            return
        self._set_status("Restoring updater…")

        def work():
            self._log("  " + CameraSetup.restore(cs))
            self._set_status("CameraSetup.exe restored")
        self._worker(work)


def main():
    App().mainloop()
    return 0
