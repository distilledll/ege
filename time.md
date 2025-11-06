``` python
# render_tk.py — исправленная версия
import threading
import queue
import time
from typing import Dict, List
from .models import InferenceResult
from .config import Settings
from loguru import logger
import tkinter as tk
from PIL import Image, ImageTk
import numpy as np
import cv2
import math


class CanvasSlot:
    def __init__(self, parent, row, col, title, min_w=320, min_h=240):
        self.frame = tk.Frame(parent, bd=1, relief=tk.RAISED, bg="black")
        # используем grid внутри parent (parent может быть frame внутри canvas)
        self.frame.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")

        # Truncate long titles
        display_title = title if len(title) <= 70 else title[:67] + "..."
        self.title = display_title
        self.label = tk.Label(self.frame, text=display_title, bg="black", fg="white", font=("Arial", 8))
        self.label.pack(side=tk.TOP, anchor="w", fill="x")

        # Canvas для кадра
        self.canvas = tk.Canvas(self.frame, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # Meta label
        self.meta_text = tk.StringVar()
        self.meta_label = tk.Label(self.frame, textvariable=self.meta_text, anchor="w", justify=tk.LEFT,
                                   bg="black", fg="gray", font=("Arial", 7))
        self.meta_label.pack(side=tk.BOTTOM, anchor="w", fill="x")

        # store references
        self.img_ref = None     # ссылка на PhotoImage, чтобы GC не удалил
        self.img_obj = None     # id объекта в canvas
        self.last_seq = -1

        # last frame for resize redraw
        self.last_frame = None
        self.last_meta = None

        # minimal sizes
        self.min_w = min_w
        self.min_h = min_h

        # prevent geometry managers from shrinking children unexpectedly
        try:
            self.canvas.config(width=self.min_w, height=self.min_h)
            self.canvas.pack_propagate(False)
            self.frame.pack_propagate(False)
            self.frame.grid_propagate(False)
        except Exception:
            # some parents may behave differently; ignore if unsupported
            pass

        # Bind resize to redraw last frame
        self.canvas.bind("<Configure>", self._on_resize)

    def _on_resize(self, event):
        if self.last_frame is not None and self.last_meta is not None:
            # redraw with the new canvas size
            self._draw_frame(self.last_frame, self.last_meta)

    def show_frame(self, frame: np.ndarray, meta: dict):
        """Public: show frame (numpy BGR) and meta dict"""
        if frame is None:
            return
        self.last_frame = frame
        self.last_meta = meta
        # Draw immediately (safe from Tk mainloop because called inside .after in render)
        self._draw_frame(frame, meta)

    def _draw_frame(self, frame: np.ndarray, meta: dict):
        # ensure frame is valid
        if frame is None:
            return
        # BGR -> RGB
        try:
            img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        except Exception:
            # if frame is not BGR (e.g. grayscale), try to handle
            try:
                if frame.ndim == 2:
                    img = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
                else:
                    img = frame
            except Exception:
                return

        frame_h, frame_w = img.shape[:2]

        # Get canvas size, but guard if not yet computed
        canvas_width = max(self.canvas.winfo_width(), self.min_w)
        canvas_height = max(self.canvas.winfo_height(), self.min_h)

        # Avoid zero division
        if frame_w == 0 or frame_h == 0:
            return

        # Calculate scaling to fit canvas while keeping aspect ratio
        scale_w = canvas_width / frame_w
        scale_h = canvas_height / frame_h
        scale = min(scale_w, scale_h)

        new_w = max(1, int(frame_w * scale))
        new_h = max(1, int(frame_h * scale))

        pil = Image.fromarray(img)
        try:
            resample = Image.Resampling.LANCZOS
        except AttributeError:
            resample = Image.LANCZOS if hasattr(Image, 'LANCZOS') else Image.BICUBIC
        pil = pil.resize((new_w, new_h), resample)

        tkimg = ImageTk.PhotoImage(pil)

        # draw centered
        try:
            self.canvas.delete("all")
            # create_image returns an object id — сохраняем его и ссылку на PhotoImage
            self.img_obj = self.canvas.create_image(canvas_width // 2, canvas_height // 2, image=tkimg, anchor="center")
            self.img_ref = tkimg
        except Exception:
            # If canvas not yet properly realized, keep image ref to avoid GC and try pack/update
            self.img_ref = tkimg

        # Update metadata text
        mt = f"seq:{meta.get('seq','')} proc:{meta.get('proc_time',0):.3f} model:{meta.get('model','')}"
        self.meta_text.set(mt)
        # Force idle tasks so users see update quickly
        try:
            self.canvas.update_idletasks()
        except Exception:
            pass


class TkRender:
    def __init__(self, cfg: Settings, urls: List[str], parent_frame=None):
        self.cfg = cfg
        self.urls = urls or []
        self.results_buffer = queue.Queue()
        self._stop_event = threading.Event()
        self._thread = None
        self.root = None
        self.slots: Dict[str, CanvasSlot] = {}
        self.parent_frame = parent_frame

        # Minimum slot size (can be tuned)
        self.min_slot_width = 320
        self.min_slot_height = 240

        # scroll widgets (optional)
        self.scroll_canvas = None
        self.scroll_frame = None
        self.scrollbar = None

        # layout
        self._calculate_layout()

    def _calculate_layout(self):
        # simple layout: limit columns to 3 by default
        self.cols = min(max(1, len(self.urls)), 3)

    def push_result(self, res: InferenceResult):
        try:
            if self.results_buffer.full():
                try:
                    _ = self.results_buffer.get_nowait()
                except queue.Empty:
                    pass
            self.results_buffer.put_nowait(res)
        except queue.Full:
            pass

    def start(self):
        if self.parent_frame:
            self._setup_in_parent()
        else:
            # Note: creating Tk from a non-main thread is platform-dependent.
            # The original code used a thread; keep this behaviour to minimize changes.
            self._thread = threading.Thread(target=self._tk_loop, daemon=False, name="TkRender")
            self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self.root and not self.parent_frame:
            try:
                self.root.after(100, self.root.quit)
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=2.0)

    def _setup_in_parent(self):
        """Embed render inside provided parent frame (e.g. gui.grid_frame) using a scrollable area"""
        self.root = self.parent_frame.winfo_toplevel()

        # create scrollable canvas inside parent_frame
        self.scroll_canvas = tk.Canvas(self.parent_frame, bg="black", highlightthickness=0)
        self.scrollbar = tk.Scrollbar(self.parent_frame, orient="vertical", command=self.scroll_canvas.yview)
        self.scroll_canvas.configure(yscrollcommand=self.scrollbar.set)

        self.scrollbar.pack(side="right", fill="y")
        self.scroll_canvas.pack(side="left", fill="both", expand=True)

        self.scroll_frame = tk.Frame(self.scroll_canvas, bg="black")
        self.scroll_canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")

        def on_frame_configure(event):
            try:
                self.scroll_canvas.configure(scrollregion=self.scroll_canvas.bbox("all"))
            except Exception:
                pass

        self.scroll_frame.bind("<Configure>", on_frame_configure)

        # mousewheel support (simple)
        def on_mousewheel(event):
            # event.delta on Windows; on Linux may need event.num / event.delta handling
            try:
                self.scroll_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except Exception:
                pass

        self.root.bind_all("<MouseWheel>", on_mousewheel)

        # layout
        rows = math.ceil(len(self.urls) / self.cols)
        for r in range(rows):
            self.scroll_frame.rowconfigure(r, weight=1)
        for c in range(self.cols):
            self.scroll_frame.columnconfigure(c, weight=1)

        # create slots in scroll_frame
        for idx, url in enumerate(self.urls):
            r = idx // self.cols
            c = idx % self.cols
            slot = CanvasSlot(self.scroll_frame, r, c, title=url, min_w=self.min_slot_width, min_h=self.min_slot_height)
            # ensure min size on canvas inside slot
            try:
                slot.canvas.config(width=self.min_slot_width, height=self.min_slot_height)
                slot.canvas.pack_propagate(False)
            except Exception:
                pass
            self.slots[url] = slot

        # start pulling results
        self.root.after(50, self._pull_results)

    def _tk_loop(self):
        # create top-level window
        self.root = tk.Tk()
        self.root.title("Multi Player — RT-DETR")

        # scrollable layout like in _setup_in_parent
        self.scroll_canvas = tk.Canvas(self.root, bg="black", highlightthickness=0)
        self.scrollbar = tk.Scrollbar(self.root, orient="vertical", command=self.scroll_canvas.yview)
        self.scroll_canvas.configure(yscrollcommand=self.scrollbar.set)

        self.scrollbar.pack(side="right", fill="y")
        self.scroll_canvas.pack(side="left", fill="both", expand=True)

        self.scroll_frame = tk.Frame(self.scroll_canvas, bg="black")
        self.scroll_canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")

        def on_frame_configure(event):
            try:
                self.scroll_canvas.configure(scrollregion=self.scroll_canvas.bbox("all"))
            except Exception:
                pass

        self.scroll_frame.bind("<Configure>", on_frame_configure)

        def on_mousewheel(event):
            try:
                self.scroll_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except Exception:
                pass

        self.root.bind_all("<MouseWheel>", on_mousewheel)

        # create grid of slots
        rows = math.ceil(len(self.urls) / self.cols)
        for r in range(rows):
            self.scroll_frame.rowconfigure(r, weight=1)
        for c in range(self.cols):
            self.scroll_frame.columnconfigure(c, weight=1)

        for idx, url in enumerate(self.urls):
            r = idx // self.cols
            c = idx % self.cols
            slot = CanvasSlot(self.scroll_frame, r, c, title=url, min_w=self.min_slot_width, min_h=self.min_slot_height)
            try:
                slot.canvas.config(width=self.min_slot_width, height=self.min_slot_height)
                slot.canvas.pack_propagate(False)
            except Exception:
                pass
            self.slots[url] = slot

        self.root.after(50, self._pull_results)
        self.root.mainloop()

    def _pull_results(self):
        # called from Tk mainloop context
        try:
            while not self.results_buffer.empty():
                res: InferenceResult = self.results_buffer.get_nowait()

                # sanity checks
                if res is None or not hasattr(res, "url"):
                    continue
                # ensure frame exists and not empty
                if getattr(res, "annotated_frame", None) is None:
                    logger.warning(f"No frame from {getattr(res, 'url', '<unknown>')}")
                    continue
                # fetch slot
                slot = self.slots.get(res.url)
                if slot:
                    slot.last_seq = res.seq
                    meta = {"seq": res.seq, **(res.metadata or {})}
                    try:
                        slot.show_frame(res.annotated_frame, meta)
                    except Exception:
                        logger.exception("Failed to show frame for %s", res.url)
        except Exception as e:
            logger.exception("Render pull error: {}", e)

        if not self._stop_event.is_set() and self.root:
            try:
                self.root.after(50, self._pull_results)
            except Exception:
                pass

```
