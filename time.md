Отлично, теперь видно, почему даже с фиксацией размера CanvasSlot всё сжимается.
Причина — вот в этой строчке в gui.py:

self.grid_frame.pack(side="right", fill="both", expand=True)


Когда ты добавляешь десятки стримов, Tkinter пытается «упихнуть» всё в grid_frame, который растягивается внутри root, и grid() внутри render_tk равномерно делит всю площадь между слотами.
Из-за этого каждый Frame (а в нём и Canvas) получает долю ширины окна — хоть 10 пикселей.

🔧 Исправление (рабочее решение)

Нужно, чтобы render_tk не использовал адаптивное деление (weight=1), а применял фиксированный размер слотов и скроллинг.
Вот минимальные правки, которые решают сжатие во всех случаях:

✅ 1. В render_tk.py — в CanvasSlot.__init__ после self.canvas.pack(...):

``` python
# зафиксируем минимальные размеры
self.canvas.config(width=320, height=240)
self.canvas.pack_propagate(False)
self.frame.pack_propagate(False)
self.frame.grid_propagate(False)
```

✅ 2. В render_tk.py — в _setup_in_parent (для встроенного режима):

Заменяй блок с конфигурацией строк/столбцов на такой:

``` python
def _setup_in_parent(self):
    self.root = self.parent_frame.winfo_toplevel()

    # ограничим кол-во колонок
    self.cols = min(len(self.urls), 3)
    rows = math.ceil(len(self.urls) / self.cols)

    # создаём скроллируемый холст
    self.scroll_canvas = tk.Canvas(self.parent_frame, bg="black", highlightthickness=0)
    self.scrollbar = tk.Scrollbar(self.parent_frame, orient="vertical", command=self.scroll_canvas.yview)
    self.scroll_canvas.configure(yscrollcommand=self.scrollbar.set)

    self.scrollbar.pack(side="right", fill="y")
    self.scroll_canvas.pack(side="left", fill="both", expand=True)

    self.scroll_frame = tk.Frame(self.scroll_canvas, bg="black")
    self.scroll_canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")

    def on_frame_configure(event):
        self.scroll_canvas.configure(scrollregion=self.scroll_canvas.bbox("all"))

    self.scroll_frame.bind("<Configure>", on_frame_configure)

    # создаём CanvasSlot с фиксированным размером
    for idx, url in enumerate(self.urls):
        r = idx // self.cols
        c = idx % self.cols
        slot = CanvasSlot(self.scroll_frame, r, c, title=url)
        slot.canvas.config(width=self.min_slot_width, height=self.min_slot_height)
        slot.canvas.pack_propagate(False)
        slot.frame.pack_propagate(False)
        slot.frame.grid_propagate(False)
        self.slots[url] = slot

    self.root.after(50, self._pull_results)
```

✅ 3. В gui.py ничего менять не нужно,

но если хочешь, чтобы правая часть (grid_frame) не давила левую панель,
можно заменить:

self.grid_frame.pack(side="right", fill="both", expand=True)


на

self.grid_frame.pack(side="right", fill="both", expand=True, padx=8, pady=8)


или добавить минимальный размер окна:

self.root.minsize(1280, 720)


💡 В итоге:

каждый поток будет занимать слот 320×240;

при большом числе — появится прокрутка;

сетка больше не будет схлопываться независимо от количества потоков.

Хочешь, я соберу для тебя короткий diff (готовый патч .patch), который можно применить прямо к текущим файлам, чтобы не копировать вручную?
