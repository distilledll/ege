Хорошо — нашёл причину: я в прошлых патчах жёстко **фикcировал размеры `Canvas`** (через `canvas.config(width=..., height=...)` и `pack_propagate(False)`), поэтому при растягивании окна они НЕ увеличиваются — остаются маленькими и «статичными». Решение: **убрать жёсткую фиксацию размеров у `Canvas`**, оставить только минимальные размеры у сетки (через `rowconfigure/columnconfigure(..., minsize=...)`) и сделать правильный обработчик ресайза, чтобы кадры масштабировались по реальным размерам `Canvas`.

Ниже готовый, заменяемый фрагмент — вставь **вместо текущего класса `CanvasSlot`** и обнови небольшую константу в `TkRender.__init__`:

1. В `render_tk.py` — в начале `TkRender.__init__` поменяй минимумы на ~2× больше (как просил):

```python
# раньше: 320x240
self.min_slot_width = 640
self.min_slot_height = 480
```

2. Полностью замени класс `CanvasSlot` на этот (копируй и вставляй):

```python
class CanvasSlot:
    def __init__(self, parent, row, col, title, min_w=640, min_h=480):
        self.frame = tk.Frame(parent, bd=1, relief=tk.RAISED, bg="black")
        # разместить фрейм в гриде родителя и позволить растягиваться
        self.frame.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")

        display_title = title if len(title) <= 70 else title[:67] + "..."
        self.title = display_title
        self.label = tk.Label(self.frame, text=display_title, bg="black", fg="white", font=("Arial", 8))
        self.label.pack(side=tk.TOP, anchor="w", fill="x")

        # Canvas — НЕ фиксируем width/height здесь, пусть растягивается с frame
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

        # НЕ фиксируем размер canvas жёстко — удаляем canvas.config(width=...,height=...) и pack_propagate(False)
        # но ставим minsize на родительскую сетку (делается в _setup_in_parent/_tk_loop)

        # bind resize both on canvas and on frame (so window resize triggers redraw)
        self.canvas.bind("<Configure>", self._on_resize)
        self.frame.bind("<Configure>", self._on_resize)

        # draw immediate placeholder so user sees the slot exists
        self._draw_placeholder()

    def _draw_placeholder(self):
        try:
            ph = np.zeros((self.min_h, self.min_w, 3), dtype=np.uint8) + 40  # dark gray
            mt = {"seq": "", "proc_time": 0.0, "model": ""}
            self._draw_frame(ph, mt)
        except Exception:
            pass

    def _on_resize(self, event):
        # debounce to avoid hammering while resizing
        if self.last_frame is None or self.last_meta is None:
            return
        if hasattr(self, "_resize_job"):
            try:
                self.canvas.after_cancel(self._resize_job)
            except Exception:
                pass
        self._resize_job = self.canvas.after(100, lambda: self._draw_frame(self.last_frame, self.last_meta))

    def show_frame(self, frame: np.ndarray, meta: dict):
        if frame is None:
            return
        self.last_frame = frame
        self.last_meta = meta
        # call draw immediately (called from Tk mainloop)
        self._draw_frame(frame, meta)

    def _draw_frame(self, frame: np.ndarray, meta: dict):
        if frame is None:
            return

        # convert to RGB
        try:
            img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        except Exception:
            try:
                if frame.ndim == 2:
                    img = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
                else:
                    img = frame
            except Exception:
                return

        fh, fw = img.shape[:2]
        if fw == 0 or fh == 0:
            return

        # IMPORTANT: use actual canvas size (so image expands with window)
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()

        # If widget not realized yet, fallback to min sizes
        if canvas_width <= 1 or canvas_height <= 1:
            canvas_width = self.min_w
            canvas_height = self.min_h

        # scale keeping aspect
        scale_w = canvas_width / fw
        scale_h = canvas_height / fh
        scale = min(scale_w, scale_h)

        new_w = max(1, int(fw * scale))
        new_h = max(1, int(fh * scale))

        try:
            pil = Image.fromarray(img)
            try:
                resample = Image.Resampling.LANCZOS
            except Exception:
                resample = Image.LANCZOS if hasattr(Image, "LANCZOS") else Image.BICUBIC
            pil = pil.resize((new_w, new_h), resample)
            tkimg = ImageTk.PhotoImage(pil)
        except Exception:
            return

        # draw centered
        try:
            self.canvas.delete("all")
            self.img_obj = self.canvas.create_image(canvas_width // 2, canvas_height // 2, image=tkimg, anchor="center")
            self.img_ref = tkimg
            # ensure coords set
            self.canvas.coords(self.img_obj, canvas_width // 2, canvas_height // 2)
        except Exception:
            # keep reference anyway
            self.img_ref = tkimg

        mt = f"seq:{meta.get('seq','')} proc:{meta.get('proc_time',0):.3f} model:{meta.get('model','')}"
        try:
            self.meta_text.set(mt)
        except Exception:
            pass

        try:
            self.canvas.update_idletasks()
        except Exception:
            pass
```

3. В `_setup_common_scroll` / `_setup_in_parent` / `_tk_loop` (там, где ты делаешь `rowconfigure` / `columnconfigure`) — убедись, что ты задаёшь `minsize` и `weight=1` для строк/столбцов. Пример (у тебя есть похожий — просто обнови minsize под новые значения):

```python
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
```

4. Убедись, что НИГДЕ больше в коде не остаётся строк вида:

```python
slot.canvas.config(width=..., height=...)
slot.canvas.pack_propagate(False)
```

или замени их на **комментарии** — они блокируют авторасширение.

---

## Что это даст

* Слоты по умолчанию станут **в 2 раза больше** (640×480).
* При растягивании окна `Canvas` будет **расти вместе с `Frame`** и кадры будут масштабироваться под новый размер.
* Дебаунс ресайза предотвращает дергание и лишние перерасчёты при перетаскивании границ окна.

---

Сделай эти правки и перезапусти. Если хочешь, могу прямо сейчас показать патч/diff для твоего `render_tk.py` (готов к вставке) — скажи «кидай diff» и я его выдам.
