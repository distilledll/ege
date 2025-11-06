``` python
# render_tk.py — исправленная версия с диагностикой и защитами
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
        self.frame.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")

        display_title = title if len(title) <= 70 else title[:67] + "..."
        self.title = display_title
        self.label = tk.Label(self.frame, text=display_title, bg="black", fg="white", font=("Arial", 8))
        self.label.pack(side=tk.TOP, anchor="w", fill="x")

        self.canvas = tk.Canvas(self.frame, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.meta_text = tk.StringVar()
        self.meta_label = tk.Label(self.frame, textvariable=self.meta_text, anchor="w", justify=tk.LEFT,
                                   bg="black", fg="gray", font=("Arial", 7))
        self.meta_label.pack(side=tk.BOTTOM, anchor="w", fill="x")

        # references to prevent GC
        self.img_ref = None
        self.img_obj = None
        self.last_seq = -1

        self.last_frame = None
        self.last_meta = None

        self.min_w = min_w
        self.min_h = min_h

        # prevent shrinking by geometry managers
        try:
            self.canvas.config(width=self.min_w, height=self.min_h)
            self.canvas.pack_propagate(False)
            self.frame.pack_propagate(False)
            self.frame.grid_propagate(False)
        except Exception:
            pass

        # bind resize
        self.canvas.bind("<Configure>", self._on_resize)

        # draw immediate placeholder so user sees the slot exists
        self._draw_placeholder()

    def _draw_placeholder(self):
        # simple gray placeholder image
        try:
            ph = np.zeros((self.min_h, self.min_w, 3), dtype=np.uint8) + 40  # dark gray
            mt = {"seq": "", "proc_time": 0.0, "model": ""}
            self._draw_frame(ph, mt)
        except Exception:
            pass

    def _on_resize(self, event):
        if self.last_frame is not None and self.last_meta is not None:
            self._draw_frame(self.last_frame, self.last_meta)

    def show_frame(self, frame: np.ndarray, meta: dict):
        if frame is None:
            return
        self.last_frame = frame
        self.last_meta = meta
        # safe redraw (called from Tk mainloop)
        self._draw_frame(frame, meta)

    def _draw_frame(self, frame: np.ndarray, meta: dict):
        # validate frame
        if frame is None:
            return

        # convert to RGB
        try:
            img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        except Exception:
            # try grayscale
            try:
                if frame.ndim == 2:
                    img = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
                else:
                    img = frame
            except Exception:
                logger.debug("CanvasSlot: failed to convert frame to RGB")
                return

        frame_h, frame_w = img.shape[:2]
        if frame_w == 0 or frame_h == 0:
            return

        # get canvas size (use min if not ready)
        canvas_width = max(self.canvas.winfo_width(), self.min_w)
        canvas_height = max(self.canvas.winfo_height(), self.min_h)

        # compute scale keeping aspect
        scale_w = canvas_width / frame_w
        scale_h = canvas_height / frame_h
        scale = min(scale_w, scale_h)

        new_w = max(1, int(frame_w * scale))
        new_h = max(1, int(frame_h * scale))

        try:
            pil = Image.fromarray(img)
            try:
                resample = Image.Resampling.LANCZOS
            except Exception:
                resample = Image.LANCZOS if hasattr(Image, "LANCZOS") else Image.BICUBIC
            pil = pil.resize((new_w, new_h), resample)
            tkimg = ImageTk.PhotoImage(pil)
        except Exception as e:
            logger.exception("Failed to prepare PhotoImage: {}", e)
            return

        # draw centered and save references
        try:
            # clear and create image
            self.canvas.delete("all")
            self.img_obj = self.canvas.create_image(canvas_width // 2, canvas_height // 2, image=tkimg, anchor="center")
            self.img_ref = tkimg
            # ensure coords set (in case canvas size changed after create)
            self.canvas.coords(self.img_obj, canvas_width // 2, canvas_height // 2)
        except Exception as e:
            # fallback: keep reference to avoid GC
            logger.debug("CanvasSlot: create_image failed, keeping img_ref: {}", e)
            self.img_ref = tkimg

        # update meta text
        mt = f"seq:{meta.get('seq','')} proc:{meta.get('proc_time',0):.3f} model:{meta.get('model','')}"
        try:
            self.meta_text.set(mt)
        except Exception:
            pass

        # force pending GUI updates
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

        self.min_slot_width = 320
        self.min_slot_height = 240

        self.scroll_canvas = None
        self.scroll_frame = None
        self.scrollbar = None

        self._calculate_layout()

    def _calculate_layout(self):
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

    def _setup_common_scroll(self, container):
        """Create scroll_canvas + scroll_frame inside container and return them"""
        scroll_canvas = tk.Canvas(container, bg="black", highlightthickness=0)
        scrollbar = tk.Scrollbar(container, orient="vertical", command=scroll_canvas.yview)
        scroll_canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        scroll_canvas.pack(side="left", fill="both", expand=True)

        scroll_frame = tk.Frame(scroll_canvas, bg="black")
        scroll_canvas.create_window((0, 0), window=scroll_frame, anchor="nw")

        def on_frame_configure(event):
            try:
                scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all"))
            except Exception:
                pass

        scroll_frame.bind("<Configure>", on_frame_configure)

        # mouse wheel support (basic)
        def on_mousewheel(event):
            try:
                # on Windows event.delta is multiple of 120
                scroll_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except Exception:
                pass

        # bind to top-level to ensure wheel works even when canvas not focused
        container.winfo_toplevel().bind_all("<MouseWheel>", on_mousewheel)

        return scroll_canvas, scroll_frame, scrollbar

    def _setup_in_parent(self):
        self.root = self.parent_frame.winfo_toplevel()
        self.scroll_canvas, self.scroll_frame, self.scrollbar = self._setup_common_scroll(self.parent_frame)

        # set minsize for rows / columns so slots don't shrink to 1px
        rows = math.ceil(len(self.urls) / self.cols)
        for r in range(rows):
            try:
                self.scroll_frame.rowconfigure(r, weight=1, minsize=self.min_slot_height)
            except Exception:
                pass
        for c in range(self.cols):
            try:
                self.scroll_frame.columnconfigure(c, weight=1, minsize=self.min_slot_width)
            except Exception:
                pass

        # create slots and draw initial placeholder for each
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

        # small diagnostic log
        logger.debug("Render: created {} slots (cols={})", len(self.slots), self.cols)

        # start pulling results
        self.root.after(50, self._pull_results)

    def _tk_loop(self):
        self.root = tk.Tk()
        self.root.title("Multi Player — RT-DETR")
        self.scroll_canvas, self.scroll_frame, self.scrollbar = self._setup_common_scroll(self.root)

        rows = math.ceil(len(self.urls) / self.cols)
        for r in range(rows):
            try:
                self.scroll_frame.rowconfigure(r, weight=1, minsize=self.min_slot_height)
            except Exception:
                pass
        for c in range(self.cols):
            try:
                self.scroll_frame.columnconfigure(c, weight=1, minsize=self.min_slot_width)
            except Exception:
                pass

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

        logger.debug("Render (toplevel): created {} slots (cols={})", len(self.slots), self.cols)

        self.root.after(50, self._pull_results)
        self.root.mainloop()

    def _pull_results(self):
        try:
            while not self.results_buffer.empty():
                res: InferenceResult = self.results_buffer.get_nowait()

                # quick diagnostics
                if res is None:
                    logger.debug("Render: got None result")
                    continue
                logger.debug("Render: packet from url={} seq={}", getattr(res, "url", "<no-url>"), getattr(res, "seq", -1))

                if getattr(res, "annotated_frame", None) is None or getattr(res.annotated_frame, "size", 0) == 0:
                    logger.debug("Render: empty annotated_frame for {}", res.url)
                    continue

                slot = self.slots.get(res.url)
                if slot is None:
                    # try to match by substring (sometimes URL normalization differs)
                    for k in self.slots.keys():
                        if k in res.url or res.url in k:
                            slot = self.slots.get(k)
                            break

                if not slot:
                    logger.debug("Render: no slot found for url={}", res.url)
                    continue

                slot.last_seq = res.seq
                meta = {"seq": res.seq, **(res.metadata or {})}
                try:
                    slot.show_frame(res.annotated_frame, meta)
                except Exception:
                    logger.exception("Render: failed to show frame for {}", res.url)
        except Exception as e:
            logger.exception("Render pull error: {}", e)

        if not self._stop_event.is_set() and self.root:
            try:
                self.root.after(50, self._pull_results)
            except Exception:
                pass

```
