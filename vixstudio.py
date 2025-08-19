#!/usr/bin/env python3
# vixstudio — baby ide for vixscript
# features: editor + console, open/save, run (F5), basic syntax highlight, line numbers

import os, sys, io, re, traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# make sure we can import vixscript.py from the same folder
APP_DIR = os.path.abspath(os.path.dirname(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

try:
    import vixscript  # expects vixscript.py next to this file
except Exception as e:
    messagebox.showerror("vixstudio", f"failed to import vixscript.py:\n{e}")
    raise

KEYWORDS = ("let", "print", "use")
STRING_RE = r'"([^"\\]|\\.)*"'
NUMBER_RE = r'\b\d+(\.\d+)?\b'
IDENT_RE  = r'\b[A-Za-z_][A-Za-z0-9_]*\b'

class LineNumbers(tk.Canvas):
    def __init__(self, master, text_widget, **kwargs):
        super().__init__(master, width=48, highlightthickness=0, **kwargs)
        self.text = text_widget
        self.text.bind("<<Change>>", self.redraw, add=True)
        self.text.bind("<Configure>", self.redraw, add=True)
        self.redraw()

    def redraw(self, event=None):
        self.delete("all")
        i = self.text.index("@0,0")
        while True:
            dline = self.text.dlineinfo(i)
            if dline is None:
                break
            y = dline[1]
            ln = str(i).split(".")[0]
            self.create_text(42, y, anchor="ne", text=ln, fill="#9aa0a6", font=("Consolas", 10))
            i = self.text.index(f"{i}+1line")

class VixStudio(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("vixstudio — vixscript ide")
        self.geometry("1000x700")
        self.minsize(800, 500)
        self.filename = None

        self._build_ui()
        self._bind_shortcuts()

    # ---------- UI ----------
    def _build_ui(self):
        # menu
        menubar = tk.Menu(self)
        filem = tk.Menu(menubar, tearoff=0)
        filem.add_command(label="New", command=self.new_file, accelerator="Ctrl+N")
        filem.add_command(label="Open…", command=self.open_file, accelerator="Ctrl+O")
        filem.add_command(label="Save", command=self.save_file, accelerator="Ctrl+S")
        filem.add_command(label="Save As…", command=self.save_file_as, accelerator="Ctrl+Shift+S")
        filem.add_separator()
        filem.add_command(label="Exit", command=self.quit)
        menubar.add_cascade(label="File", menu=filem)

        runm = tk.Menu(menubar, tearoff=0)
        runm.add_command(label="Run", command=self.run_code, accelerator="F5")
        menubar.add_cascade(label="Run", menu=runm)

        self.config(menu=menubar)

        # toolbar
        toolbar = ttk.Frame(self, padding=(8, 6))
        ttk.Button(toolbar, text="New", command=self.new_file).pack(side="left")
        ttk.Button(toolbar, text="Open", command=self.open_file).pack(side="left", padx=(6,0))
        ttk.Button(toolbar, text="Save", command=self.save_file).pack(side="left", padx=(6,0))
        ttk.Button(toolbar, text="Run ▶", command=self.run_code).pack(side="left", padx=(14,0))
        toolbar.pack(fill="x")

        # editor + console split
        paned = ttk.PanedWindow(self, orient="vertical")
        paned.pack(fill="both", expand=True)

        # editor frame (with line numbers)
        editor_frame = ttk.Frame(paned)
        self.text = tk.Text(
            editor_frame, wrap="none", undo=True, font=("Consolas", 12),
            background="#0d1117", foreground="#e6edf3", insertbackground="#e6edf3",
            padx=6, pady=6
        )
        self.text_scroll_y = ttk.Scrollbar(editor_frame, command=self.text.yview)
        self.text_scroll_x = ttk.Scrollbar(editor_frame, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=self.text_scroll_y.set, xscrollcommand=self.text_scroll_x.set)
        self.linenums = LineNumbers(editor_frame, self.text, background="#0b0f14")

        self.linenums.pack(side="left", fill="y")
        self.text.pack(side="top", fill="both", expand=True)
        self.text_scroll_y.pack(side="right", fill="y")
        self.text_scroll_x.pack(side="bottom", fill="x")

        # console frame
        console_frame = ttk.Frame(paned)
        self.console = tk.Text(
            console_frame, wrap="word", state="disabled", height=10,
            background="#0b0f14", foreground="#c8d1da", insertbackground="#c8d1da",
            font=("Consolas", 11), padx=6, pady=6
        )
        self.console.pack(fill="both", expand=True)

        paned.add(editor_frame, weight=3)
        paned.add(console_frame, weight=1)

        # status bar
        self.status = ttk.Label(self, text="ready", anchor="w")
        self.status.pack(fill="x")

        # tags for syntax highlight + console colors
        self.text.tag_configure("kw", foreground="#7aa2f7")
        self.text.tag_configure("num", foreground="#e0af68")
        self.text.tag_configure("str", foreground="#9ece6a")
        self.text.tag_configure("id", foreground="#c0caf5")
        self.console.tag_configure("stderr", foreground="#ff6b6b")
        self.console.tag_configure("stdout", foreground="#c8d1da")
        self.console.tag_configure("ok", foreground="#8bd5ca")

        # event bindings for highlighting + line numbers
        self.text.bind("<<Modified>>", self._on_modified)

        # sample doc
        self.text.insert("1.0", 'use math\nprint 1 + 2 * 3\n')
        self._highlight_all()
        self._set_status()

    def _bind_shortcuts(self):
        self.bind("<Control-n>", lambda e: self.new_file())
        self.bind("<Control-o>", lambda e: self.open_file())
        self.bind("<Control-s>", lambda e: self.save_file())
        self.bind("<Control-S>", lambda e: self.save_file_as())
        self.bind("<F5>", lambda e: self.run_code())

    # ---------- file ops ----------
    def new_file(self):
        self.filename = None
        self.text.delete("1.0", "end")
        self.console_clear()
        self._set_status("new file")

    def open_file(self):
        path = filedialog.askopenfilename(
            title="open vixscript",
            filetypes=[("vix files","*.vix"), ("all files","*.*")]
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self.filename = path
            self.text.delete("1.0", "end")
            self.text.insert("1.0", content)
            self.console_clear()
            self._highlight_all()
            self._set_status(f"opened {os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("open file", str(e))

    def save_file(self):
        if not self.filename:
            return self.save_file_as()
        try:
            with open(self.filename, "w", encoding="utf-8") as f:
                f.write(self.text.get("1.0", "end-1c"))
            self._set_status(f"saved {os.path.basename(self.filename)}")
        except Exception as e:
            messagebox.showerror("save file", str(e))

    def save_file_as(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".vix",
            filetypes=[("vix files","*.vix"), ("all files","*.*")]
        )
        if not path:
            return
        self.filename = path
        self.save_file()

    # ---------- console ----------
    def console_write(self, s, tag="stdout"):
        self.console.configure(state="normal")
        self.console.insert("end", s, tag)
        self.console.see("end")
        self.console.configure(state="disabled")

    def console_clear(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

    # ---------- run ----------
    def run_code(self):
        src = self.text.get("1.0", "end-1c")
        self.console_clear()
        self._set_status("running…")

        buf = io.StringIO()
        def _stdout(val):
            # vixscript's print calls this; keep newline behavior like print
            print(val, file=buf)

        try:
            # directly invoke your interpreter
            vixscript.run_code(src, stdout=_stdout)
            out = buf.getvalue()
            if out:
                self.console_write(out, "stdout")
            self.console_write("✓ finished\n", "ok")
            self._set_status("done")
        except Exception as e:
            tb = traceback.format_exc()
            self.console_write(tb, "stderr")
            self._set_status("error")

    # ---------- syntax highlight ----------
    def _on_modified(self, event=None):
        if self.text.edit_modified():
            self._highlight_visible()
            self.text.edit_modified(False)
        # notify line numbers
        self.text.event_generate("<<Change>>")

    def _clear_tags(self, start, end):
        for tag in ("kw","num","str","id"):
            self.text.tag_remove(tag, start, end)

    def _highlight_range(self, start, end):
        text = self.text.get(start, end)

        # strings
        for m in re.finditer(STRING_RE, text):
            a = f"{start}+{m.start()}c"
            b = f"{start}+{m.end()}c"
            self.text.tag_add("str", a, b)

        # numbers
        for m in re.finditer(NUMBER_RE, text):
            a = f"{start}+{m.start()}c"
            b = f"{start}+{m.end()}c"
            self.text.tag_add("num", a, b)

        # keywords + identifiers
        for m in re.finditer(IDENT_RE, text):
            word = m.group(0)
            a = f"{start}+{m.start()}c"
            b = f"{start}+{m.end()}c"
            if word in KEYWORDS:
                self.text.tag_add("kw", a, b)
            # else:
            #     self.text.tag_add("id", a, b)  # optional

    def _highlight_all(self):
        self._clear_tags("1.0","end")
        self._highlight_range("1.0","end-1c")

    def _highlight_visible(self):
        first = self.text.index("@0,0")
        last  = self.text.index("@0,%d" % self.text.winfo_height())
        self._clear_tags(first, last)
        self._highlight_range(first, last)

    # ---------- status ----------
    def _set_status(self, msg=None):
        name = os.path.basename(self.filename) if self.filename else "untitled.vix"
        self.status.config(text=f"{name} — {msg or 'ready'}")

def main():
    app = VixStudio()
    app.mainloop()

if __name__ == "__main__":
    main()
