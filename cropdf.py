import argparse
from pathlib import Path
import sys
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
import fitz

class PDFCropper:
    def __init__(self, root):
        self.root, self.doc, self.current_page = root, None, 0
        self.image_tk = self.crop_rect = self.crop_coords = None
        self.start_x = self.start_y = None
        self.space_pressed = False
        self.display_scale = 1.0
        self.img_offset_x = self.img_offset_y = 0
        self.page_rect = None
        self._resize_job = None
        self._did_set_default_geometry = False
        root.title("CroPDF")

        self.canvas = tk.Canvas(root, cursor="cross")
        self.canvas.pack(fill="both", expand=True)
        self.toolbar = tk.Frame(root)
        self.toolbar.pack(side="bottom", fill="x")

        self.btn_open = tk.Button(self.toolbar, text="Open PDF", command=self.open_pdf)
        self.btn_prev = tk.Button(self.toolbar, text="< Prev", command=self.prev_page, state="disabled")
        self.page_label = tk.Label(self.toolbar, text="Page: 0/0")
        self.btn_next = tk.Button(self.toolbar, text="Next >", command=self.next_page, state="disabled")
        self.btn_go_to = tk.Button(self.toolbar, text="Go to Page", command=self.go_to_page, state="disabled")
        self.btn_crop = tk.Button(self.toolbar, text="Crop and Save", command=self.crop_and_save, state="disabled")
        for w in [self.btn_open, self.btn_prev, self.page_label, self.btn_next, self.btn_go_to]:
            w.pack(side="left")
        self.btn_crop.pack(side="right")

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Configure>", self.on_canvas_resize)
        root.bind("<KeyPress>", self.on_key_press)
        root.bind("<KeyPress-space>", lambda e: setattr(self, 'space_pressed', True))
        root.bind("<KeyRelease-space>", lambda e: setattr(self, 'space_pressed', False))
        for seq, callback in (("<Command-o>", self.open_pdf),
                              ("<Command-s>", self.crop_and_save),
                              ("<Command-g>", self.go_to_page)):
            root.bind(seq, lambda e, cb=callback: cb())
        root.bind("<Escape>", self.deselect)

    def on_key_press(self, event):
        if not self.crop_rect or not self.crop_coords:
            if event.keysym == 'Left':
                self.prev_page()
            elif event.keysym == 'Right':
                self.next_page()
            return
        x1, y1, x2, y2 = self.crop_coords
        amt = 25 if self.space_pressed else 1
        shift = event.state & 0x0001

        if event.keysym == 'Up':
            y1, y2 = (y1, y2 - amt) if shift else (y1 - amt, y2 - amt)
        elif event.keysym == 'Down':
            y1, y2 = (y1, y2 + amt) if shift else (y1 + amt, y2 + amt)
        elif event.keysym == 'Left':
            x1, x2 = (x1, x2 - amt) if shift else (x1 - amt, x2 - amt)
        elif event.keysym == 'Right':
            x1, x2 = (x1, x2 + amt) if shift else (x1 + amt, x2 + amt)

        self.crop_coords = (x1, y1, x2, y2)
        self.canvas.coords(self.crop_rect, x1, y1, x2, y2)

    def deselect(self, event=None):
        self._delete_crop_rect()
        self.crop_rect = self.crop_coords = None
        self._update_ui()

    def open_pdf(self, path=None):
        if not path:
            path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
        if not path:
            return False
        try:
            self.doc, self.current_page = fitz.open(path), 0
        except Exception as exc:
            messagebox.showerror("Error", f"Could not open PDF: {exc}")
            return False
        self._set_default_window_geometry()
        self.show_page(0)
        self.root.focus_force()
        return True

    def _set_default_window_geometry(self):
        if self._did_set_default_geometry or not self.doc or self.doc.page_count == 0: return
        self.root.update_idletasks()
        max_w, max_h = self.root.maxsize()
        toolbar_h = self.toolbar.winfo_reqheight()
        page = self.doc.load_page(0).rect
        avail_h = max(max_h - toolbar_h, 100)
        scale = min(max_w / page.width, avail_h / page.height)
        canvas_w = max(int(page.width * scale), 300)
        canvas_h = max(int(page.height * scale), 100)
        win_w = min(canvas_w, max_w)
        win_h = min(canvas_h + toolbar_h, max_h)
        x = max((max_w - win_w) // 2, 0)
        y = max((max_h - win_h) // 2, 0)
        self.root.geometry(f"{win_w}x{win_h}+{x}+{y}")
        self._did_set_default_geometry = True

    def show_page(self, page_num):
        if not self.doc or not (0 <= page_num < self.doc.page_count): return
        self.current_page = page_num
        self.render_current_page()
        self.crop_rect = None
        self._update_ui()

    def render_current_page(self):
        if not self.doc: return
        page = self.doc.load_page(self.current_page)
        self.page_rect = page.rect
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        scale = 1.0 if cw <= 1 or ch <= 1 else min(cw / self.page_rect.width, ch / self.page_rect.height)
        self.display_scale = max(scale, 0.01)
        pix = page.get_pixmap(matrix=fitz.Matrix(self.display_scale, self.display_scale))
        self.image_tk = tk.PhotoImage(data=pix.tobytes("png"))
        self.img_offset_x = max((cw - pix.width) // 2, 0)
        self.img_offset_y = max((ch - pix.height) // 2, 0)
        self.canvas.delete("all")
        self.canvas.create_image(self.img_offset_x, self.img_offset_y, anchor="nw", image=self.image_tk)

    def on_canvas_resize(self, _event):
        if not self.doc: return
        if self._resize_job: self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(60, self._apply_resize)

    def _apply_resize(self):
        self._resize_job = None
        self.deselect()
        self.render_current_page()

    def _update_ui(self):
        if self.doc:
            n = self.doc.page_count
            self.page_label.config(text=f"Page: {self.current_page + 1}/{n}")
            self.btn_prev.config(state="normal" if self.current_page > 0 else "disabled")
            self.btn_next.config(state="normal" if self.current_page < n - 1 else "disabled")
            self.btn_go_to.config(state="normal")
            self.btn_crop.config(state="normal" if self.crop_coords else "disabled")
        else:
            self.page_label.config(text="Page: 0/0")
            for b in [self.btn_prev, self.btn_next, self.btn_go_to, self.btn_crop]: b.config(state="disabled")

    def prev_page(self):
        if self.current_page > 0: self.show_page(self.current_page - 1)

    def next_page(self):
        if self.doc and self.current_page < self.doc.page_count - 1: self.show_page(self.current_page + 1)

    def go_to_page(self):
        if self.doc and (p := simpledialog.askinteger("Go to Page", "Enter page number:",
                parent=self.root, minvalue=1, maxvalue=self.doc.page_count)):
            self.show_page(p - 1)

    def on_press(self, event):
        self.start_x, self.start_y = self._event_xy(event)
        self._delete_crop_rect()
        self.crop_rect = None

    def on_drag(self, event):
        x, y = self._event_xy(event)
        self._delete_crop_rect()
        self.crop_rect = self.canvas.create_rectangle(self.start_x, self.start_y, x, y, outline="red", width=2)

    def on_release(self, event):
        x, y = self._event_xy(event)
        self.crop_coords = (min(self.start_x, x), min(self.start_y, y), max(self.start_x, x), max(self.start_y, y))
        self.btn_crop.config(state="normal")

    def _event_xy(self, event):
        return self._clamp_to_image(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))

    def _delete_crop_rect(self):
        if self.crop_rect: self.canvas.delete(self.crop_rect)

    def _clamp_to_image(self, x, y):
        if not self.image_tk: return x, y
        x = min(max(x, self.img_offset_x), self.img_offset_x + self.image_tk.width())
        y = min(max(y, self.img_offset_y), self.img_offset_y + self.image_tk.height())
        return x, y

    def crop_and_save(self):
        if not self.doc or not self.crop_coords: return
        x1, y1, x2, y2 = self.crop_coords
        box = fitz.Rect(
            (x1 - self.img_offset_x) / self.display_scale,
            (y1 - self.img_offset_y) / self.display_scale,
            (x2 - self.img_offset_x) / self.display_scale,
            (y2 - self.img_offset_y) / self.display_scale
        ) & self.page_rect
        new_doc = fitz.open()
        new_doc.new_page(width=box.width, height=box.height).show_pdf_page(
            fitz.Rect(0, 0, box.width, box.height), self.doc, self.current_page, clip=box)
        if path := filedialog.asksaveasfilename(defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")],
                initialfile=f"cropped_page_{self.current_page + 1}.pdf"):
            try: new_doc.save(path)
            except Exception as e: messagebox.showerror("Error", f"Could not save: {e}")
            finally: new_doc.close()
        self.root.focus_force()


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Crop PDFs while preserving vector quality.")
    parser.add_argument("pdf_path", nargs="?", help="PDF file path (relative to current directory or absolute).")
    parser.add_argument("--page", type=int, help="1-based page number to open.")
    args = parser.parse_args(argv)
    if args.page is not None and args.pdf_path is None:
        parser.error("--page requires a PDF path")
    return args


def _pick_pdf_path():
    root = tk.Tk()
    root.withdraw()
    root.overrideredirect(True)
    root.attributes("-alpha", 0)
    _show(root)
    path = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
    root.destroy()
    return path


def _resolve_pdf_path(path):
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = Path.cwd() / resolved
    return resolved


def main(argv=None):
    args = _parse_args(argv)

    start_page = args.page
    if args.pdf_path:
        pdf_path = _resolve_pdf_path(args.pdf_path)
        if not pdf_path.is_file():
            print(f"Error: file not found: {pdf_path}", file=sys.stderr)
            return 2
        path = str(pdf_path)
    else:
        path = _pick_pdf_path()
        if not path:
            return 0

    root = tk.Tk()
    _show(root)
    app = PDFCropper(root)
    if not app.open_pdf(path):
        root.destroy()
        return 2
    if start_page is not None:
        if not 1 <= start_page <= app.doc.page_count:
            messagebox.showerror(
                "Invalid page",
                f"Page must be between 1 and {app.doc.page_count}.",
            )
            root.destroy()
            return 2
        app.show_page(start_page - 1)
    _show(root)
    root.mainloop()
    return 0


def _show(root): root.deiconify(); root.focus_force()


if __name__ == "__main__":
    raise SystemExit(main())
