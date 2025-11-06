def _tk_loop(self):
    self.root = tk.Tk()
    self.root.title("Multi Player — RT-DETR")

    # === Scrollable container ===
    self.scroll_canvas = tk.Canvas(self.root, bg="black", highlightthickness=0)
    self.scrollbar = tk.Scrollbar(self.root, orient="vertical", command=self.scroll_canvas.yview)
    self.scroll_canvas.configure(yscrollcommand=self.scrollbar.set)

    self.scrollbar.pack(side="right", fill="y")
    self.scroll_canvas.pack(side="left", fill="both", expand=True)

    # Frame, в который помещаются все CanvasSlot
    self.scroll_frame = tk.Frame(self.scroll_canvas, bg="black")
    self.scroll_window = self.scroll_canvas.create_window((0, 0), window=self.scroll_frame, anchor="nw")

    # === Прокрутка при изменении размера содержимого ===
    def on_frame_configure(event):
        self.scroll_canvas.configure(scrollregion=self.scroll_canvas.bbox("all"))

    def on_mousewheel(event):
        self.scroll_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    self.scroll_frame.bind("<Configure>", on_frame_configure)
    self.root.bind_all("<MouseWheel>", on_mousewheel)

    # === Логика компоновки ===
    self.cols = min(len(self.urls), 3)  # максимум 3 колонки
    rows = math.ceil(len(self.urls) / self.cols)

    for r in range(rows):
        self.scroll_frame.rowconfigure(r, weight=1)
    for c in range(self.cols):
        self.scroll_frame.columnconfigure(c, weight=1)

    # === Создание слотов ===
    for idx, url in enumerate(self.urls):
        r = idx // self.cols
        c = idx % self.cols
        slot = CanvasSlot(self.scroll_frame, r, c, title=url)

        # фиксируем минимальный размер
        slot.canvas.config(width=self.min_slot_width, height=self.min_slot_height)
        slot.canvas.pack_propagate(False)

        self.slots[url] = slot

    # === Запуск цикла обновления ===
    self.root.after(50, self._pull_results)
    self.root.mainloop()
