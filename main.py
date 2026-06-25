import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, simpledialog
import threading
import json
import os
import webbrowser
import re
from datetime import datetime

from vk_client import VKClient
from ai_agent import AIAgent, CONFIDENCE_THRESHOLD
from navigation import Navigator

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")
ZONE_GRAPH_FILE = os.path.join(os.path.dirname(__file__), "zone_graph.json")
WAIT_SENTINEL = "__WAIT__"  # сигнал "ждать следующего сообщения, ничего не отправлять"


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Stalker Bot — VK Auto Player v.1.0.0")
        self.root.geometry("980x820")
        self.root.minsize(820, 600)
        self.root.resizable(True, True)

        self.running = False
        self.thread = None
        self.config = self._load_config()

        self._setup_ui()

    def _load_config(self):
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8-sig') as f:
                return json.load(f)
        return {"token": "", "peer_id": "", "model": "llama3.2"}

    def _save_config(self):
        config = {
            "token": self.token_var.get(),
            "peer_id": self.peer_id_var.get(),
            "model": self.model_var.get(),
            "strategy": self._strategy,
            "heal_threshold": self.heal_threshold_var.get(),
            "eat_threshold": self.eat_threshold_var.get(),
            "rest_threshold": self.rest_threshold_var.get(),
            "explore_anomaly": self.explore_anomaly.get(),
            "bolt_refill": self.bolt_refill.get(),
            "bolt_threshold": self.bolt_threshold_var.get(),
            "explore_stashes": self.explore_stashes.get(),
            "fishing_enabled": self.fishing_enabled.get(),
            "fish_sell_auto": self.fish_sell_auto.get(),
        }
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    def _paste_token(self):
        try:
            text = self.root.clipboard_get()
            self.token_var.set(text.strip())
        except tk.TclError:
            messagebox.showwarning("Буфер пуст", "В буфере обмена нет текста")

    def _auth_vk(self):
        oauth_url = (
            "https://oauth.vk.com/authorize?client_id=2685278"
            "&scope=messages,offline"
            "&redirect_uri=https://oauth.vk.com/blank.html"
            "&display=page&response_type=token&revoke=1"
        )
        webbrowser.open(oauth_url)

        win = tk.Toplevel(self.root)
        win.title("Авторизация VK")
        win.geometry("520x200")
        win.grab_set()

        ttk.Label(win, text=(
            "1. В открывшемся браузере нажмите «Разрешить»\n"
            "2. Вас перекинет на пустую страницу — скопируйте полный URL из адресной строки\n"
            "3. Вставьте его сюда:"
        ), justify=tk.LEFT, wraplength=490).pack(padx=15, pady=(15, 8), anchor=tk.W)

        url_var = tk.StringVar()
        entry = ttk.Entry(win, textvariable=url_var, width=65)
        entry.pack(padx=15, pady=4, fill=tk.X)

        def paste_url():
            try:
                url_var.set(self.root.clipboard_get().strip())
            except tk.TclError:
                pass

        def confirm():
            url = url_var.get().strip()
            match = re.search(r"access_token=([^&]+)", url)
            if match:
                self.token_var.set(match.group(1))
                win.destroy()
                messagebox.showinfo("Готово", "Токен успешно получен!")
            else:
                messagebox.showerror("Ошибка", "Токен не найден в URL.\nУбедитесь, что скопировали полный адрес страницы.", parent=win)

        btn_frame = ttk.Frame(win)
        btn_frame.pack(pady=8)
        ttk.Button(btn_frame, text="Вставить URL", command=paste_url).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Получить токен", command=confirm).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Отмена", command=win.destroy).pack(side=tk.LEFT, padx=5)

    def _refresh_models(self):
        try:
            import ollama as _ollama
            models = [m.model for m in _ollama.list().models]
            if models:
                self.model_combo['values'] = models
                if self.model_var.get() not in models:
                    self.model_var.set(models[0])
            else:
                self.model_combo['values'] = ["(нет установленных моделей)"]
        except Exception:
            self.model_combo['values'] = [self.model_var.get()]

    def _toggle_token(self):
        self.show_token = not self.show_token
        self.token_entry.configure(show="" if self.show_token else "*")

    def _setup_ui(self):
        # --- Config frame ---
        cfg = ttk.LabelFrame(self.root, text="Настройки", padding=10)
        cfg.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(cfg, text="VK Токен:").grid(row=0, column=0, sticky=tk.W, pady=3)
        self.token_var = tk.StringVar(value=self.config.get("token", ""))
        self.token_entry = ttk.Entry(cfg, textvariable=self.token_var, width=60, show="*")
        self.token_entry.grid(row=0, column=1, padx=5, pady=3, sticky=tk.EW)
        self.show_token = False
        btn_frame = ttk.Frame(cfg)
        btn_frame.grid(row=0, column=2, padx=5, pady=3)
        ttk.Button(btn_frame, text="Авторизация VK", command=self._auth_vk).pack(side=tk.LEFT, padx=(0, 3))
        ttk.Button(btn_frame, text="Вставить", width=9, command=self._paste_token).pack(side=tk.LEFT, padx=(0, 3))
        ttk.Button(btn_frame, text="Показать", width=9, command=self._toggle_token).pack(side=tk.LEFT)

        ttk.Label(cfg, text="ID бота (peer_id):").grid(row=1, column=0, sticky=tk.W, pady=3)
        self.peer_id_var = tk.StringVar(value=self.config.get("peer_id", ""))
        ttk.Entry(cfg, textvariable=self.peer_id_var, width=20).grid(
            row=1, column=1, padx=5, pady=3, sticky=tk.W)
        ttk.Label(cfg, text="(число из URL чата, напр. 123456789)", foreground="gray").grid(
            row=1, column=2, padx=5, sticky=tk.W)

        ttk.Label(cfg, text="Модель Ollama:").grid(row=2, column=0, sticky=tk.W, pady=3)
        self.model_var = tk.StringVar(value=self.config.get("model", "llama3.2"))
        self.model_combo = ttk.Combobox(cfg, textvariable=self.model_var, width=30, state="readonly")
        self.model_combo.grid(row=2, column=1, padx=5, pady=3, sticky=tk.W)
        ttk.Button(cfg, text="Обновить список", command=self._refresh_models).grid(
            row=2, column=2, padx=5, pady=3, sticky=tk.W)
        self._refresh_models()

        from ai_agent import DEFAULT_STRATEGY
        self._strategy = self.config.get("strategy", DEFAULT_STRATEGY)

        cfg.columnconfigure(1, weight=1)

        # --- Controls ---
        ctrl = ttk.Frame(self.root)
        ctrl.pack(fill=tk.X, padx=10, pady=4)

        self.start_btn = ttk.Button(ctrl, text="▶  Запустить", command=self._start, width=14)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.stop_btn = ttk.Button(ctrl, text="■  Остановить", command=self._stop, state=tk.DISABLED, width=14)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        self.status_var = tk.StringVar(value="● Остановлен")
        self.status_lbl = ttk.Label(ctrl, textvariable=self.status_var, foreground="gray", font=("Segoe UI", 9, "bold"))
        self.status_lbl.pack(side=tk.RIGHT, padx=5)

        # --- Секции настроек (5 столбиков в одной строке) ---
        sections_row = ttk.Frame(self.root)
        sections_row.pack(fill=tk.X, padx=10, pady=(0, 4))

        # ── Авто-действия ──────────────────────────────────────────
        act_frame = ttk.LabelFrame(sections_row, text="Авто-действия", padding=6)
        act_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 3))

        hp_row = ttk.Frame(act_frame)
        hp_row.pack(anchor=tk.W, pady=(0, 1))
        ttk.Label(hp_row, text="HP:", foreground="gray").pack(side=tk.LEFT)
        self.hp_display_var = tk.StringVar(value="— (?%)")
        ttk.Label(hp_row, textvariable=self.hp_display_var,
                  foreground="#2a7a2a", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(2, 0))

        self.food_display_var = tk.StringVar(value="еда: ?")
        ttk.Label(act_frame, textvariable=self.food_display_var,
                  foreground="#555", font=("Segoe UI", 8)).pack(anchor=tk.W, pady=(0, 4))

        ttk.Separator(act_frame).pack(fill=tk.X, pady=(0, 4))

        self.heal_threshold_var = tk.IntVar(value=self.config.get("heal_threshold", 30))
        r1 = ttk.Frame(act_frame); r1.pack(anchor=tk.W, pady=1)
        ttk.Label(r1, text="Лечиться при HP ≤").pack(side=tk.LEFT)
        ttk.Spinbox(r1, from_=1, to=99, width=4,
                    textvariable=self.heal_threshold_var).pack(side=tk.LEFT, padx=2)
        ttk.Label(r1, text="%", foreground="gray").pack(side=tk.LEFT)

        self.eat_threshold_var = tk.IntVar(value=self.config.get("eat_threshold", 30))
        r2 = ttk.Frame(act_frame); r2.pack(anchor=tk.W, pady=1)
        ttk.Label(r2, text="Есть при сытости ≤").pack(side=tk.LEFT)
        ttk.Spinbox(r2, from_=1, to=99, width=4,
                    textvariable=self.eat_threshold_var).pack(side=tk.LEFT, padx=2)
        ttk.Label(r2, text="%", foreground="gray").pack(side=tk.LEFT)

        self.rest_threshold_var = tk.IntVar(value=self.config.get("rest_threshold", 50))
        r3 = ttk.Frame(act_frame); r3.pack(anchor=tk.W, pady=1)
        ttk.Label(r3, text="Отдыхать при HP ≤").pack(side=tk.LEFT)
        ttk.Spinbox(r3, from_=1, to=99, width=4,
                    textvariable=self.rest_threshold_var).pack(side=tk.LEFT, padx=2)
        ttk.Label(r3, text="% (без боя)", foreground="gray").pack(side=tk.LEFT)

        # ── Аномалии ───────────────────────────────────────────────
        anom_frame = ttk.LabelFrame(sections_row, text="Аномалии", padding=6)
        anom_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 3))

        self.explore_anomaly = tk.BooleanVar(value=self.config.get("explore_anomaly", True))
        ttk.Checkbutton(anom_frame, text="Исследовать аномалии",
                        variable=self.explore_anomaly).pack(anchor=tk.W)

        bolt_row = ttk.Frame(anom_frame)
        bolt_row.pack(anchor=tk.W, pady=(3, 0))
        self.bolt_refill = tk.BooleanVar(value=self.config.get("bolt_refill", True))
        ttk.Checkbutton(bolt_row, text="Пополнять болты при <",
                        variable=self.bolt_refill).pack(side=tk.LEFT)
        self.bolt_threshold_var = tk.IntVar(value=self.config.get("bolt_threshold", 50))
        ttk.Spinbox(bolt_row, from_=1, to=9999, width=5,
                    textvariable=self.bolt_threshold_var).pack(side=tk.LEFT, padx=2)
        ttk.Label(bolt_row, text="шт.", foreground="gray").pack(side=tk.LEFT)

        self.bolt_count_var = tk.StringVar(value="болты: ?")
        ttk.Label(anom_frame, textvariable=self.bolt_count_var,
                  foreground="#555", font=("Segoe UI", 9)).pack(anchor=tk.W, pady=(4, 0))

        # ── Схроны ─────────────────────────────────────────────────
        stash_frame = ttk.LabelFrame(sections_row, text="Схроны", padding=6)
        stash_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 3))

        self.explore_stashes = tk.BooleanVar(value=self.config.get("explore_stashes", True))
        ttk.Checkbutton(stash_frame, text="Исследовать схроны,\nмашины, вертолёты",
                        variable=self.explore_stashes).pack(anchor=tk.W)

        # ── Рыбалка ────────────────────────────────────────────────
        fish_frame = ttk.LabelFrame(sections_row, text="Рыбалка", padding=6)
        fish_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 3))

        self.fishing_enabled = tk.BooleanVar(value=self.config.get("fishing_enabled", True))
        ttk.Checkbutton(fish_frame, text="Рыбачить",
                        variable=self.fishing_enabled).pack(anchor=tk.W)

        self.fish_sell_auto = tk.BooleanVar(value=self.config.get("fish_sell_auto", True))
        ttk.Checkbutton(fish_frame, text="Автопродажа рыбы\nпри < 5 мест в садке",
                        variable=self.fish_sell_auto).pack(anchor=tk.W, pady=(3, 0))

        self.fish_count_var = tk.StringVar(value="садок: ?")
        ttk.Label(fish_frame, textvariable=self.fish_count_var,
                  foreground="#555", font=("Segoe UI", 9)).pack(anchor=tk.W, pady=(4, 0))


        # --- Панель оценки ---
        rate_frame = ttk.LabelFrame(self.root, text="Оценка последнего решения ИИ", padding=6)
        rate_frame.pack(fill=tk.X, padx=10, pady=(0, 4))

        self.last_decision_var = tk.StringVar(value="—")
        ttk.Label(rate_frame, textvariable=self.last_decision_var, width=55,
                  anchor=tk.W, font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=5)
        ttk.Button(rate_frame, text="👍 Верно", width=10,
                   command=self._rate_good).pack(side=tk.LEFT, padx=3)
        ttk.Button(rate_frame, text="👎 Неверно", width=10,
                   command=self._rate_bad).pack(side=tk.LEFT, padx=3)

        self._last_game_text = ""
        self._last_buttons = []
        self._last_choice = ""
        self._user_choice = None
        self._user_event = threading.Event()
        self._in_anomaly_heal = False   # True пока лечимся внутри аномалии
        self._in_combat_heal = False    # True пока лечимся внутри боя
        self._last_hp_pct: int | None = None  # последнее известное HP для сообщений без HP
        self._last_hunger: tuple[int, int] | None = None  # последняя сытость для сообщений без показателей
        self._buy_food_mode = False     # True: в режиме покупки еды у костра
        self._buy_food_deficit = 0      # оставшийся дефицит сытости для покупки
        self._last_buy_buttons: list = []  # кэш кнопок меню покупки еды
        self._bolt_refilling = False    # True: едем на Свалку пополнять болты
        self._bolt_return_zone = ""     # зона для возврата после пополнения болтов
        self._fish_selling = False          # True: идём в деревню продавать рыбу
        self._fish_sell_menu_entered = False  # True: уже входили в меню продажи рыб
        self._fish_return_zone = ""         # зона для возврата после продажи рыбы
        self._food_counts: dict[str, int] = {}  # последние известные количества еды
        self._vk_client = None  # VKClient, доступный из основного потока для ручной отправки
        self.nav = Navigator(ZONE_GRAPH_FILE)

        # --- Log ---
        log_frame = ttk.LabelFrame(self.root, text="Лог", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.log = scrolledtext.ScrolledText(
            log_frame, wrap=tk.WORD, height=18, font=("Consolas", 9), state=tk.DISABLED)
        self.log.pack(fill=tk.BOTH, expand=True)

        self.log.bind("<Control-c>", self._copy_log_selection)
        self.log.bind("<Button-3>", self._show_log_menu)

        self.log.tag_configure("vk", foreground="#1a6b1a")
        self.log.tag_configure("ai", foreground="#1a3d99")
        self.log.tag_configure("send", foreground="#8b4a00")
        self.log.tag_configure("error", foreground="#cc0000")
        self.log.tag_configure("info", foreground="#555555")

        self._log("Приложение запущено. Введите настройки и нажмите Запустить.", "info")

        # --- Панель ручного управления (всегда видима под логом) ---
        self._control_frame = ttk.LabelFrame(self.root, text="Управление", padding=6)
        self._control_frame.pack(fill=tk.X, padx=10, pady=(0, 5))

        inp_row = ttk.Frame(self._control_frame)
        inp_row.pack(fill=tk.X, pady=(0, 5))

        self.manual_input_var = tk.StringVar()
        self._manual_entry = ttk.Entry(inp_row, textvariable=self.manual_input_var,
                                       font=("Segoe UI", 10))
        self._manual_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self._manual_entry.bind("<Return>",
                                lambda e: self._manual_send(self.manual_input_var.get()))

        ttk.Button(inp_row, text="Отправить",
                   command=lambda: self._manual_send(self.manual_input_var.get())).pack(side=tk.LEFT)

        ttk.Label(self._control_frame, text="Кнопки бота:",
                  foreground="gray", font=("Segoe UI", 8)).pack(anchor=tk.W)
        self._quick_btn_frame = ttk.Frame(self._control_frame)
        self._quick_btn_frame.pack(fill=tk.X, pady=(2, 0))
        ttk.Label(self._quick_btn_frame, text="— нет кнопок —",
                  foreground="gray", font=("Segoe UI", 8)).pack(side=tk.LEFT)

        # --- Инлайн-панель решений (показывается между логом и управлением) ---
        self.decision_frame = ttk.LabelFrame(self.root, text="⚠ Требуется ваш выбор", padding=8)
        # NOT packed here — shown via _show_inline_decision (с before=_control_frame)

    def _show_inline_decision(self, title: str, build_fn):
        """Показывает панель решений между логом и панелью управления."""
        self.decision_frame.configure(text=title)
        for w in self.decision_frame.winfo_children():
            w.destroy()
        build_fn(self.decision_frame)
        self.decision_frame.pack(fill=tk.X, padx=10, pady=(0, 5),
                                 before=self._control_frame)

    def _hide_inline_decision(self):
        """Скрывает панель решений."""
        self.decision_frame.pack_forget()

    def _manual_send(self, text: str):
        """Отправляет сообщение боту вручную (из основного потока)."""
        text = text.strip()
        if not text:
            return
        if self._vk_client is None:
            self._log("⚠ Бот не запущен — отправка невозможна", "error")
            return
        self.manual_input_var.set("")
        self._log(f"[РУЧНОЙ ВВОД] → «{text}»", "send")
        threading.Thread(
            target=lambda: self._vk_client.send_message(text),
            daemon=True
        ).start()

    def _update_quick_buttons(self, buttons: list):
        """Обновляет быстрые кнопки в панели управления (вызывается из main thread)."""
        for w in self._quick_btn_frame.winfo_children():
            w.destroy()
        if not buttons:
            ttk.Label(self._quick_btn_frame, text="— нет кнопок —",
                      foreground="gray", font=("Segoe UI", 8)).pack(side=tk.LEFT)
            return
        for btn in buttons:
            label = btn['label']
            ttk.Button(
                self._quick_btn_frame, text=label,
                command=lambda l=label: self._manual_send(l)
            ).pack(side=tk.LEFT, padx=2, pady=1)

    def _rate_good(self):
        if not self._last_choice:
            return
        self.ai_agent.add_feedback(
            self._last_game_text, self._last_buttons, self._last_choice, is_good=True)
        self._log(f"Оценка: 👍 «{self._last_choice}» отмечено как верное решение", "ai")

    def _rate_bad(self):
        if not self._last_choice:
            return
        win = tk.Toplevel(self.root)
        win.title("Что нужно было сделать?")
        win.geometry("420x220")
        win.grab_set()
        win.attributes("-topmost", True)

        ttk.Label(win, text=f'ИИ выбрал: «{self._last_choice}»\n\nКакую кнопку нужно было нажать?',
                  justify=tk.LEFT, wraplength=390).pack(padx=15, pady=10)

        btn_frame = ttk.Frame(win)
        btn_frame.pack(padx=15, fill=tk.X)
        correction_var = tk.StringVar()

        for label in self._last_buttons:
            b = ttk.Radiobutton(btn_frame, text=label, variable=correction_var, value=label)
            b.pack(anchor=tk.W)

        ttk.Label(win, text="Или опишите текстом:").pack(padx=15, anchor=tk.W)
        custom_var = tk.StringVar()
        ttk.Entry(win, textvariable=custom_var, width=40).pack(padx=15, anchor=tk.W)

        def confirm():
            corr = custom_var.get().strip() or correction_var.get() or None
            self.ai_agent.add_feedback(
                self._last_game_text, self._last_buttons, self._last_choice,
                is_good=False, correction=corr)
            self._log(f"Оценка: 👎 «{self._last_choice}» неверно" +
                      (f", надо «{corr}»" if corr else ""), "error")
            win.destroy()

        ttk.Button(win, text="Сохранить", command=confirm).pack(pady=8)

    def _ask_user(self, game_text: str, buttons: list) -> str | None:
        """Показывает инлайн-панель когда ИИ не уверен. Вызывается из main thread."""
        self._user_choice = None
        self._user_event.clear()

        def build(frame):
            preview = game_text[:300].replace('\n', ' ')
            ttk.Label(frame,
                      text="ИИ не смог определить правильное действие. Выберите кнопку:",
                      font=("Segoe UI", 9, "bold")).pack(anchor=tk.W, pady=(0, 3))
            ttk.Label(frame, text=preview, wraplength=920, foreground="gray",
                      justify=tk.LEFT, font=("Segoe UI", 9)).pack(anchor=tk.W, pady=(0, 5))

            choice_var = tk.StringVar(value=buttons[0] if buttons else WAIT_SENTINEL)
            rf = ttk.Frame(frame)
            rf.pack(anchor=tk.W, fill=tk.X)
            for label in buttons:
                ttk.Radiobutton(rf, text=label, variable=choice_var, value=label).pack(anchor=tk.W)
            ttk.Separator(rf).pack(fill=tk.X, pady=3)
            ttk.Radiobutton(rf, text="⏳ Ждать следующего сообщения (ничего не нажимать)",
                            variable=choice_var, value=WAIT_SENTINEL).pack(anchor=tk.W)

            def confirm():
                self._user_choice = choice_var.get()
                self._user_event.set()
                self._hide_inline_decision()

            def skip():
                self._user_choice = WAIT_SENTINEL
                self._user_event.set()
                self._hide_inline_decision()

            bf = ttk.Frame(frame)
            bf.pack(pady=(6, 0), anchor=tk.W)
            ttk.Button(bf, text="Выполнить", command=confirm).pack(side=tk.LEFT, padx=(0, 5))
            ttk.Button(bf, text="Пропустить (ждать)", command=skip).pack(side=tk.LEFT)

        self._show_inline_decision("⚠ ИИ не уверен — выберите действие", build)

    _ANOMALY_KW_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "anomaly_keywords.json")
    _ANOMALY_KW_BUILTIN = [
        "аномалия пробудилась", "аномалия пробуждена", "аномалия активирована",
        "аномалия активна", "аномалия ожила", "аномалия реагирует",
        "аномалия начала", "аномалия проснулась", "пробуждение аномалии",
    ]

    def _load_anomaly_keywords(self) -> list:
        try:
            with open(self._ANOMALY_KW_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _save_anomaly_keyword(self, phrase: str):
        data = self._load_anomaly_keywords()
        phrase_low = phrase.lower().strip()
        if phrase_low and phrase_low not in data:
            data.append(phrase_low)
            with open(self._ANOMALY_KW_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def _is_anomaly_awakened(self, text: str) -> bool:
        text_low = text.lower()
        all_kw = self._ANOMALY_KW_BUILTIN + self._load_anomaly_keywords()
        return any(kw in text_low for kw in all_kw)

    def _add_anomaly_keyword_dialog(self):
        phrase = simpledialog.askstring(
            "Добавить фразу аномалии",
            "Скопируйте из лога фрагмент текста,\nпри котором нужно ждать решения пользователя:",
            parent=self.root
        )
        if phrase and phrase.strip():
            self._save_anomaly_keyword(phrase.strip())
            self._log(f"Добавлена фраза-триггер аномалии: «{phrase.strip()}»", "info")


    def _parse_current_location(self, text: str) -> str | None:
        """Извлекает название текущей зоны из сообщения типа '🚩Локация: Вход в болотистые сопки : ...'"""
        m = re.search(r'локация\s*[:：]\s*([^\n:]+)', text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return None

    def _parse_bolt_count(self, text: str) -> tuple[int, int | None] | None:
        """Парсит количество болтов. Возвращает (cur, max) или (cur, None), или None."""
        text_low = text.lower()
        m = re.search(r'болт[ыов]*[:\s]+(\d+)/(\d+)', text_low)
        if m:
            return int(m.group(1)), int(m.group(2))
        m = re.search(r'болт[ыов]*[:\s]+(\d+)', text_low)
        if m:
            return int(m.group(1)), None
        # "У вас 149 болтов" — число стоит перед словом
        m = re.search(r'(\d+)\s+болт[ыов]*', text_low)
        if m:
            return int(m.group(1)), None
        return None

    def _parse_sadok_info(self, text: str) -> tuple[int, int] | None:
        """Возвращает (текущий, максимум) для садка или None."""
        m = re.search(r'садок[:\s]+(\d+)/(\d+)', text.lower())
        if m:
            return int(m.group(1)), int(m.group(2))
        return None

    def _parse_sadok_free(self, text: str) -> int | None:
        """Возвращает количество свободных мест в садке или None если не найдено."""
        info = self._parse_sadok_info(text)
        if info:
            cur, total = info
            return total - cur
        # "мест в садке: 0"
        m = re.search(r'мест в садке[:\s]+(\d+)', text.lower())
        if m:
            return int(m.group(1))
        return None

    def _is_fishing(self, text: str, buttons: list | None = None) -> bool:
        keywords = ["рыбалк", "удочк", "садок", "клёв", "клев", "рыб", "закинуть удочку", "ловить рыбу"]
        text_low = text.lower()
        if any(kw in text_low for kw in keywords):
            return True
        if buttons:
            button_text = " ".join(b['label'].lower() for b in buttons)
            return any(kw in button_text for kw in (
                "закинуть удочку", "забросить удочку", "окончить рыбалку", "подсечь"
            ))
        return False

    def _ask_sadok_full(self, game_text: str, buttons: list) -> str | None:
        """Инлайн-панель при полном садке — спрашивает пользователя ловить ли дальше."""
        self._user_choice = None
        self._user_event.clear()

        def show_dialog():
            def build(frame):
                ttk.Label(frame,
                          text="🐟 Садок заполнен (свободных мест < 1)! Продолжать ловить или выйти?",
                          font=("Segoe UI", 9, "bold"), justify=tk.LEFT).pack(anchor=tk.W, pady=(0, 5))

                choice_var = tk.StringVar(value=buttons[0] if buttons else WAIT_SENTINEL)
                rf = ttk.Frame(frame)
                rf.pack(anchor=tk.W, fill=tk.X)
                for lbl in buttons:
                    ttk.Radiobutton(rf, text=lbl, variable=choice_var, value=lbl).pack(anchor=tk.W)
                ttk.Separator(rf).pack(fill=tk.X, pady=3)
                ttk.Radiobutton(rf, text="⏳ Ждать следующего сообщения",
                                variable=choice_var, value=WAIT_SENTINEL).pack(anchor=tk.W)

                def confirm():
                    self._user_choice = choice_var.get()
                    self._user_event.set()
                    self._hide_inline_decision()

                def cancel():
                    self._user_choice = WAIT_SENTINEL
                    self._user_event.set()
                    self._hide_inline_decision()

                bf = ttk.Frame(frame)
                bf.pack(pady=(6, 0), anchor=tk.W)
                ttk.Button(bf, text="Выполнить", command=confirm).pack(side=tk.LEFT, padx=(0, 5))
                ttk.Button(bf, text="Пропустить (ждать)", command=cancel).pack(side=tk.LEFT)

            self._show_inline_decision("🐟 Садок заполнен!", build)

        self.root.after(0, show_dialog)
        self._user_event.wait(timeout=180)
        return self._user_choice

    def _parse_hp_info(self, text: str) -> tuple[int, int] | None:
        """Возвращает (текущее HP, максимум) или None."""
        text_low = text.lower()
        for pattern in (r'здоровье[:\s]+(\d+)/(\d+)', r'персонаж[:\s]+(\d+)/(\d+)'):
            m = re.search(pattern, text_low)
            if m:
                cur, total = int(m.group(1)), int(m.group(2))
                if total > 0:
                    return cur, total
        return None

    def _parse_hp_percent(self, text: str) -> int | None:
        """Извлекает процент HP из текста. Возвращает 0-100 или None если не найдено."""
        info = self._parse_hp_info(text)
        if info:
            cur, total = info
            return round(cur / total * 100)
        return None

    def _is_hunger_critical(self, text: str) -> bool:
        """Возвращает True если сытость ≤ 10 (срочно нужно есть)."""
        m = re.search(r'сытость[:\s]+(\d+)', text, re.IGNORECASE)
        if m:
            return int(m.group(1)) <= 10
        return False

    def _parse_hunger(self, text: str) -> tuple[int, int] | None:
        """Возвращает (текущая_сытость, максимум) или None если не найдено."""
        m = re.search(r'сытость[:\s]+(\d+)/(\d+)', text, re.IGNORECASE)
        if m:
            return int(m.group(1)), int(m.group(2))
        m = re.search(r'сытость[:\s]+(\d+)', text, re.IGNORECASE)
        if m:
            return int(m.group(1)), 100
        return None

    # Кнопки-подтверждения — нажимаются автоматически без ИИ
    CONFIRM_BUTTONS = {
        "записка", "ок", "ок!", "принять", "закрыть", "продолжить",
        "понял", "хорошо", "понятно", "далее", "следующий", "готово",
        "назад", "выход", "закрыть записку",
        "подсечь", "🪝 подсечь",
        "о предмете", "об оружии", "о броне", "о снаряжении",
    }

    def _auto_confirm_button(self, labels: list) -> str | None:
        """Если все кнопки — подтверждения, возвращает первую."""
        clean = [l.lower().strip() for l in labels]
        if all(c in self.CONFIRM_BUTTONS for c in clean):
            return labels[0]
        if len(labels) == 1 and clean[0] in self.CONFIRM_BUTTONS:
            return labels[0]
        return None

    # Схроны / машины / вертолёты — ключевые слова для обнаружения и раскопки
    STASH_SEARCH_KEYWORDS = [
        # Обнаружение схрона (начальная фаза — когда только кнопка "Прервать")
        "похоже здесь есть схрон", "есть схрон", "рыхлая земля", "вы решили откопать",
        "потребуется 20 минут", "потребуется 8 минут", "набором инструментов",
        "здесь есть схрон", "тут есть схрон",
        # Раскопка схрона (в процессе)
        "схрон найден", "раскапываем схрон", "раскопка схрона", "копаем схрон",
        "схрон раскапывается", "идёт раскопка", "идет раскопка",
        # Машина
        "обыскиваем машину", "обыск машины", "осматриваем машину",
        "похоже здесь есть машина", "здесь стоит машина", "нашли машину",
        # Вертолёт
        "обыскиваем вертолёт", "обыскиваем вертолет", "обыск вертолёта",
        "осматриваем вертолёт", "осматриваем вертолет",
        "похоже здесь есть вертолёт", "нашли вертолёт",
    ]

    def _is_stash_search(self, text: str, buttons: list) -> bool:
        """True если идёт обнаружение / раскопка схрона, обыск машины или вертолёта."""
        text_low = text.lower()
        has_kw = any(kw in text_low for kw in self.STASH_SEARCH_KEYWORDS)
        has_cancel = any(b['label'].lower().strip() == "прервать" for b in buttons)
        # Fallback: единственная кнопка "Прервать" + текст упоминает схрон/машину/вертолёт
        if not has_kw and has_cancel:
            has_kw = any(kw in text_low for kw in ("схрон", "машин", "вертол", "откопать", "обыск"))
        return has_kw and has_cancel

    # Тёмный сталкер — авто-уход
    DARK_STALKER_KEYWORDS = [
        "тёмный сталкер", "темный сталкер",
        "сердец чернобыля", "сердца чернобыля",
        "покупай, но знай", "тёмный торговец", "темный торговец",
    ]

    def _is_dark_stalker(self, text: str) -> bool:
        text_low = text.lower()
        return any(kw in text_low for kw in self.DARK_STALKER_KEYWORDS)

    TRADER_CONTEXT_KEYWORDS = [
        "торговец", "торговца", "торговцем", "торговец:",
        "товар", "товары", "ассортимент", "что есть",
        "предлож", "уникальное предложение", "стоимость:", "монет",
        "ежели чем ценным обживёшься", "ежели чем ценным обживешься",
    ]
    TRADER_ASK_KEYWORDS = ["а что есть", "что есть", "покажи товар", "товары", "ассортимент"]
    TRADER_ALLOWED_KEYWORDS = ["аптеч", "болт"]
    TRADER_REJECT_KEYWORDS = [
        "откажусь", "отказаться", "не надо", "нет", "уйти", "назад",
        "выход", "пройти мимо",
    ]
    TRADER_ACCEPT_KEYWORDS = ["давай, согласен", "согласен", "купить", "беру"]

    def _choose_trader_action(self, text: str, buttons: list) -> str | None:
        """
        Жёсткая политика торговца:
        - при встрече сначала спрашиваем ассортимент;
        - покупаем только аптечки и болты;
        - остальные предложения отклоняем без участия ИИ.
        """
        if not buttons:
            return None

        text_low = text.lower()
        label_pairs = [(b['label'], b['label'].lower().strip()) for b in buttons]
        ask_btn = next(
            (label for label, label_low in label_pairs
             if any(kw in label_low for kw in self.TRADER_ASK_KEYWORDS)),
            None
        )
        if ask_btn:
            return ask_btn

        has_trader_text = any(kw in text_low for kw in self.TRADER_CONTEXT_KEYWORDS)
        has_trader_button = any(
            any(kw in label_low for kw in (
                self.TRADER_ASK_KEYWORDS
                + self.TRADER_REJECT_KEYWORDS
                + self.TRADER_ACCEPT_KEYWORDS
            ))
            for _, label_low in label_pairs
        )
        if not (has_trader_text and has_trader_button):
            return None

        allowed_offer = any(kw in text_low for kw in self.TRADER_ALLOWED_KEYWORDS)
        allowed_buy_btn = next(
            (label for label, label_low in label_pairs
             if any(kw in label_low for kw in self.TRADER_ALLOWED_KEYWORDS)
             and not any(kw in label_low for kw in self.TRADER_REJECT_KEYWORDS)),
            None
        )
        if allowed_buy_btn:
            return allowed_buy_btn

        if allowed_offer:
            accept_btn = next(
                (label for label, label_low in label_pairs
                 if any(kw in label_low for kw in self.TRADER_ACCEPT_KEYWORDS)),
                None
            )
            if accept_btn:
                return accept_btn

        return next(
            (label for label, label_low in label_pairs
             if any(kw in label_low for kw in self.TRADER_REJECT_KEYWORDS)),
            None
        )

    # Кнопки, требующие подтверждения пользователя перед нажатием
    ESCAPE_BUTTONS = {
        "побег", "убежать", "бежать", "отступить", "убегаем", "отход",
        "прервать", "пройти мимо",
        "оставить ящик", "⬅ оставить ящик", "оставить сундук", "уйти",
        "ввести число", "окончить рыбалку", "покинуть охоту",
        "в хижину",
    }

    def _is_escape_button(self, label: str) -> bool:
        return label.lower().strip() in self.ESCAPE_BUTTONS

    def _confirm_escape(self, label: str, buttons: list) -> str:
        """Показывает диалог подтверждения побега. Возвращает выбранную кнопку."""
        self._user_choice = None
        self._user_event.clear()

        def show_dialog():
            win = tk.Toplevel(self.root)
            win.title("Подтверждение побега")
            win.geometry("460x280")
            win.attributes("-topmost", True)
            win.grab_set()

            ttk.Label(win,
                      text=f"ИИ хочет нажать «{label}»\n\nПодтвердите или выберите другое действие:",
                      font=("Segoe UI", 10, "bold"), justify=tk.LEFT).pack(pady=(14, 6), padx=15)

            choice_var = tk.StringVar(value=label)
            btn_area = ttk.Frame(win)
            btn_area.pack(padx=15, fill=tk.X)
            for lbl in buttons:
                ttk.Radiobutton(btn_area, text=lbl, variable=choice_var, value=lbl).pack(anchor=tk.W)
            ttk.Separator(btn_area).pack(fill=tk.X, pady=4)
            ttk.Radiobutton(btn_area, text="⏳ Ждать следующего сообщения (ничего не нажимать)",
                            variable=choice_var, value=WAIT_SENTINEL).pack(anchor=tk.W)

            def confirm():
                self._user_choice = choice_var.get()
                self._user_event.set()
                win.destroy()

            def cancel():
                self._user_choice = WAIT_SENTINEL
                self._user_event.set()
                win.destroy()

            bf = ttk.Frame(win)
            bf.pack(pady=10)
            ttk.Button(bf, text="Выполнить", command=confirm).pack(side=tk.LEFT, padx=5)
            ttk.Button(bf, text="Пропустить (ждать)", command=cancel).pack(side=tk.LEFT, padx=5)
            win.protocol("WM_DELETE_WINDOW", cancel)

        self.root.after(0, show_dialog)
        self._user_event.wait(timeout=120)
        return self._user_choice or WAIT_SENTINEL

    # --- Сундуки и ящики ---

    CHEST_KEYWORDS = [
        "потребуется", "ключ", "замок", "стальной ящик", "ящик", "сундук",
        "отмычка", "сломать замок",
    ]

    def _is_chest_situation(self, text: str) -> bool:
        text_low = text.lower()
        return ("ключ" in text_low or "отмычка" in text_low) and (
            "ящик" in text_low or "замок" in text_low or "сундук" in text_low
        )

    def _chest_auto_choice(self, text: str, buttons: list) -> str | None:
        """Возвращает кнопку для открытия ящика или None если не определить."""
        text_low = text.lower()

        # Парсим сколько нужно ключей
        needed = 0
        m = re.search(r'потребуется\s+(\d+)\s+ключ', text_low)
        if m:
            needed = int(m.group(1))

        # Парсим сколько есть ключей
        available = 0
        m = re.search(r'у вас\s+(\d+)\s+ключ', text_low)
        if m:
            available = int(m.group(1))

        labels_low = {b['label'].lower(): b['label'] for b in buttons}

        # Если ключей достаточно — жмём кнопку с ключами
        if available >= needed and needed > 0:
            for label_low, label in labels_low.items():
                if "ключ" in label_low and "оставить" not in label_low:
                    return label
            # fallback: любая кнопка с числом ключей
            for label_low, label in labels_low.items():
                if re.search(r'\d+\s*ключ', label_low):
                    return label

        # Ключей нет или не хватает — взлом
        for priority in ["отмычка", "сломать замок", "взломать"]:
            if priority in labels_low:
                return labels_low[priority]

        return None

    # Кнопки аптечек и входа в меню лечения — фильтруются при HP > 20%
    MEDKIT_BUTTONS = {
        "аптечка", "армейская", "научная", "аптечка х5", "арм. х5",
        "армейская х5", "научная х5",
        "бинт", "научная аптечка", "использовать аптечку",
        "➕ лечение", "лечение",   # меню лечения — не открывать без нужды
    }

    # Кнопки подменю выбора аптечки (появляются после нажатия "➕ Лечение")
    MEDKIT_SUBMENU_BUTTONS = frozenset({
        "аптечка", "армейская", "научная",
        "аптечка х5", "армейская х5", "научная х5", "арм. х5",
        "бинт", "научная аптечка",
    })

    # Еда у костра: название (нижний регистр) → восстановление голода
    FOOD_VALUES: dict[str, int] = {
        "хлеб": 15,
        "колбаса": 20,
        "сгущенка": 30,
        "сгущённка": 30,
    }

    # (ключевое слово для поиска, отображаемое имя)
    FOOD_NAMES: list[tuple[str, str]] = [
        ("колбас", "Колбаса"),
        ("хлеб",   "Хлеб"),
        ("сгущ",   "Сгущёнка"),
        ("горошек", "Горошек"),
    ]

    def _parse_food_counts(self, text: str) -> dict[str, int]:
        """Парсит количество еды из сообщения вида 'Колбаса (1)'. Возвращает {display_name: count}."""
        result = {}
        for kw, name in self.FOOD_NAMES:
            m = re.search(kw + r'[^\s(]*\s*\((\d+)\)', text, re.IGNORECASE)
            if m:
                result[name] = int(m.group(1))
        return result

    def _is_medkit_submenu(self, buttons: list) -> bool:
        """True если открыто подменю выбора аптечки."""
        labels_low = {b['label'].lower().strip() for b in buttons}
        return bool(labels_low & self.MEDKIT_SUBMENU_BUTTONS)

    def _is_food_buy_screen(self, buttons: list) -> bool:
        """True если это экран покупки еды (кнопки вида 'Колбаса х1', 'Хлеб х1' etc.)"""
        buy_keys = frozenset(self.FOOD_VALUES.keys())
        return any(
            ("х" in b['label'].lower() and any(k in b['label'].lower() for k in buy_keys))
            for b in buttons
        )

    def _is_food_submenu(self, buttons: list) -> bool:
        """True если доступны кнопки еды для поедания (НЕ экран покупки)."""
        if self._is_food_buy_screen(buttons):
            return False
        food_keys = frozenset(self.FOOD_VALUES.keys())
        return any(
            any(k in b['label'].lower() for k in food_keys)
            for b in buttons
        )

    def _choose_food(self, buttons: list, hunger_cur: int, hunger_max: int) -> str | None:
        """
        Выбирает оптимальную еду чтобы максимально заполнить голод без перерасхода:
        - Из вариантов без перерасхода — берём наибольшее восстановление
        - Если все выходят за максимум — берём наименьшую (минимум потерь)
        - Возвращает None если голод уже полный
        """
        deficit = hunger_max - hunger_cur
        if deficit <= 0:
            return None

        food_buttons: list[tuple[str, int]] = []
        for b in buttons:
            lbl_low = b['label'].lower().strip()
            for food_name, food_val in self.FOOD_VALUES.items():
                if food_name in lbl_low:
                    food_buttons.append((b['label'], food_val))
                    break

        if not food_buttons:
            return None

        no_overshoot = [(lbl, val) for lbl, val in food_buttons if val <= deficit]
        if no_overshoot:
            return max(no_overshoot, key=lambda x: x[1])[0]
        return min(food_buttons, key=lambda x: x[1])[0]

    def _choose_medkit(self, buttons: list, hp_pct: int | None) -> str | None:
        """
        Выбирает оптимальную аптечку:
        - При HP < 30%: x5 обычных если есть, иначе x1 обычная
        - Если нет обычных: армейская x1
        - Если нет армейских: научная x1
        - Возвращает None если аптечек нет вообще
        """
        lmap = {b['label'].lower().strip(): b['label'] for b in buttons}
        hp = hp_pct if hp_pct is not None else 20  # нет данных → считаем HP низким

        # Обычные аптечки (приоритет)
        if hp < 30 and "аптечка х5" in lmap:
            return lmap["аптечка х5"]
        if "аптечка" in lmap:
            return lmap["аптечка"]

        # Армейские (если нет обычных)
        if "армейская" in lmap:
            return lmap["армейская"]

        # Научные (если нет ни обычных, ни армейских)
        if "научная" in lmap:
            return lmap["научная"]

        return None  # аптечек нет

    # Кнопки атаки — авто-выбираются в бою при HP > 20%
    COMBAT_PRIORITY_BUTTONS = ["очередь", "стрельба на бегу", "стрелять", "атаковать", "ударить"]

    def _is_anomaly_active(self, text: str, buttons: list) -> bool:
        """True когда персонаж работает с аномалией (есть кнопка броска болта)."""
        labels_low = {b['label'].lower() for b in buttons}
        return "кинуть болт" in labels_low or "бросить болт" in labels_low

    # Кнопки которые бот никогда не нажимает
    IGNORED_BUTTONS = {
        "👤 инвентарь", "инвентарь", "📚 чат игроков", "чат игроков",
        "чат с игроками", "📚чат игроков",
    }

    def _filter_buttons(self, buttons: list) -> list:
        return [b for b in buttons
                if b['label'].lower().strip() not in self.IGNORED_BUTTONS]

    def _is_inventory_full(self, text: str) -> bool:
        keywords = [
            "инвентарь полон", "мест в инвентаре: 0", "нет свободного места",
            "инвентарь заполнен", "садок заполнен", "мест: 0",
            "нет места в инвентаре", "предмет не помещается"
        ]
        text_low = text.lower()
        return any(kw in text_low for kw in keywords)

    def _copy_log_selection(self, event=None):
        try:
            selected = self.log.get(tk.SEL_FIRST, tk.SEL_LAST)
            self.root.clipboard_clear()
            self.root.clipboard_append(selected)
        except tk.TclError:
            pass
        return "break"

    def _copy_log_all(self):
        text = self.log.get("1.0", tk.END)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def _show_log_menu(self, event):
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Копировать выделенное", command=self._copy_log_selection)
        menu.add_command(label="Копировать всё", command=self._copy_log_all)
        menu.post(event.x_root, event.y_root)

    def _log(self, text: str, tag: str = "info"):
        def _insert():
            self.log.configure(state=tk.NORMAL)
            ts = datetime.now().strftime("%H:%M:%S")
            prefix = {"vk": "[ВК]", "ai": "[ИИ]", "send": "[>>]", "error": "[!!]", "info": "[--]"}.get(tag, "[--]")
            lines = text.splitlines()
            self.log.insert(tk.END, f"{ts} {prefix} {lines[0]}\n", tag)
            for extra in lines[1:]:
                self.log.insert(tk.END, f"         {extra}\n", tag)
            self.log.see(tk.END)
            self.log.configure(state=tk.DISABLED)

        self.root.after(0, _insert)

    def _set_status(self, text: str, color: str):
        self.root.after(0, lambda: (
            self.status_var.set(text),
            self.status_lbl.configure(foreground=color)
        ))

    def _start(self):
        if not self.token_var.get().strip():
            messagebox.showerror("Ошибка", "Введите VK токен")
            return
        if not self.peer_id_var.get().strip():
            messagebox.showerror("Ошибка", "Введите peer_id бота")
            return
        try:
            int(self.peer_id_var.get().strip())
        except ValueError:
            messagebox.showerror("Ошибка", "peer_id должен быть числом")
            return

        self._save_config()
        self.running = True
        self.ai_agent = AIAgent(self.model_var.get().strip(), strategy=self._strategy)
        self.start_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        self._set_status("● Работает", "green")

        self.thread = threading.Thread(target=self._run_bot, daemon=True)
        self.thread.start()

    def _stop(self):
        self.running = False
        self.start_btn.configure(state=tk.NORMAL)
        self.stop_btn.configure(state=tk.DISABLED)
        self._set_status("● Остановлен", "gray")
        self._log("Бот остановлен.", "info")

    def _reset_ai(self):
        if hasattr(self, 'ai_agent'):
            self.ai_agent.reset_context()
            self._log("Контекст ИИ сброшен.", "info")

    def _run_bot(self):
        try:
            peer_id = int(self.peer_id_var.get().strip())
            vk = VKClient(self.token_var.get().strip(), peer_id)
            self._vk_client = vk

            self._log("Подключение к VK Long Poll...", "info")
            self._log(f"Слушаем peer_id={peer_id}", "info")

            for message_text, buttons, photo_url in vk.listen(lambda: self.running):
                if not self.running:
                    break

                # Показываем полный текст в логе (важно для поиска фраз аномалий)
                for line in message_text.splitlines():
                    if line.strip():
                        self._log(f"Бот: {line}", "vk")

                if photo_url:
                    if self.ai_agent.vision:
                        self._log("Получена карта — анализирую...", "ai")
                    else:
                        self._log("Получена карта (текстовая модель — картинка игнорируется)", "info")

                # Детектор болтов
                bolt_info = self._parse_bolt_count(message_text)
                if bolt_info is not None:
                    b_cur, b_max = bolt_info
                    bolt_str = f"{b_cur}/{b_max}" if b_max is not None else str(b_cur)
                    self.root.after(0, lambda s=bolt_str: self.bolt_count_var.set(f"болты: {s}"))
                    thr = self.bolt_threshold_var.get()
                    if self.bolt_refill.get():
                        is_full = (b_max is not None and b_cur >= b_max) or b_cur >= thr
                        if self._bolt_refilling and is_full:
                            self._bolt_refilling = False
                            self._log(
                                f"✅ Болты пополнены ({bolt_str}) — возвращаемся в «{self._bolt_return_zone}»",
                                "info",
                            )
                        elif not self._bolt_refilling and not self._bolt_return_zone and b_cur < thr:
                            self._bolt_refilling = True
                            self._bolt_return_zone = self.nav.current_zone or ""
                            self._log(
                                f"🔩 Болтов мало ({b_cur} < {thr}) — идём на Свалку пополняться",
                                "info",
                            )
                    elif b_cur < 50:
                        self._log(f"⚠ Болтов мало: {b_cur} шт.", "error")

                # Детектор садка
                sadok_info = self._parse_sadok_info(message_text)
                if sadok_info is not None:
                    s_cur, s_total = sadok_info
                    s_free = s_total - s_cur
                    self.root.after(0, lambda c=s_cur, t=s_total:
                                    self.fish_count_var.set(f"садок: {c}/{t}"))
                    if (self.fish_sell_auto.get()
                            and not self._fish_selling
                            and not self._fish_return_zone
                            and s_free < 5):
                        self._fish_selling = True
                        self._fish_return_zone = self.nav.current_zone or ""
                        self._log(
                            f"🐟 Садок почти полный ({s_free} мест) — едем продавать рыбу",
                            "info",
                        )

                # Детектор количества еды
                food_counts = self._parse_food_counts(message_text)
                if food_counts:
                    self._food_counts.update(food_counts)
                    parts = [f"{name}: {self._food_counts[name]}"
                             for _, name in self.FOOD_NAMES
                             if name in self._food_counts]
                    self.root.after(0, lambda s=" | ".join(parts):
                                    self.food_display_var.set(s))

                # Мониторинг голода
                _h = self._parse_hunger(message_text)
                if _h:
                    self._last_hunger = _h
                    _h_cur, _h_max = _h
                    _h_pct = round(_h_cur / _h_max * 100) if _h_max > 0 else 0
                    _eat_thr = self.eat_threshold_var.get()
                    if _h_pct <= 10:
                        self._log(
                            f"⚠ Голод критический: {_h_cur}/{_h_max} ({_h_pct}%) — срочно к костру!", "error")
                    elif _h_pct <= _eat_thr:
                        self._log(
                            f"🍞 Голод: {_h_cur}/{_h_max} ({_h_pct}%) ≤ {_eat_thr}% — нужно поесть", "info")

                # Обновляем текущую зону
                loc = self._parse_current_location(message_text)
                if loc:
                    changed, transition = self.nav.update_location(loc)
                    if changed:
                        if transition:
                            from_z, dir_k, to_z = transition
                            self._log(
                                f"🗺 Карта: «{from_z}» --[{dir_k}]--> «{to_z}»", "info")
                        self._log(f"📍 Зона: «{loc}»", "info")

                # Детектор пробуждённой аномалии
                if self._is_anomaly_awakened(message_text) and buttons:
                    labels = [b['label'] for b in buttons]
                    self._log("⚠ АНОМАЛИЯ ПРОБУЖДЕНА — жду вашего решения...", "error")
                    self._user_choice = None
                    self._user_event.clear()
                    self.root.after(0, lambda t=message_text, b=labels:
                                    self._ask_user(t, b))
                    self._user_event.wait(timeout=300)
                    choice = self._user_choice or labels[0]
                    if choice == WAIT_SENTINEL:
                        self._log("⏳ Ждём следующего сообщения (аномалия).", "info")
                        continue
                    self._log(f"Решение пользователя (аномалия): «{choice}»", "send")
                    self.ai_agent.add_feedback(message_text, labels, choice, is_good=True)
                    vk.send_message(choice)
                    continue

                # Детектор полного инвентаря
                if self._is_inventory_full(message_text):
                    self._log("⚠ ИНВЕНТАРЬ ПОЛОН — требуется ручная продажа предметов!", "error")
                    self.root.after(0, lambda: messagebox.showwarning(
                        "Инвентарь полон",
                        "Инвентарь персонажа заполнен!\n\nИдите в город и продайте предметы вручную,\nзатем нажмите Запустить снова."
                    ))
                    self.root.after(0, self._stop)
                    break

                # Рыбалка
                if self._is_fishing(message_text, buttons) and buttons:
                    free = self._parse_sadok_free(message_text)

                    # Рыбалка отключена — ищем кнопку выхода
                    if not self.fishing_enabled.get():
                        exit_btn = next(
                            (b['label'] for b in buttons if any(
                                kw in b['label'].lower()
                                for kw in ("вернуться", "уйти", "⬅", "назад", "выйти", "окончить")
                            )),
                            None
                        )
                        if exit_btn:
                            self._log(f"🎣 Рыбалка отключена — выходим: «{exit_btn}»", "ai")
                            vk.send_message(exit_btn)
                            self._log(f"Отправлено: «{exit_btn}»", "send")
                        else:
                            self._log("🎣 Рыбалка отключена — кнопки выхода нет, ждём", "info")
                        continue

                    # Садок заполнен — ждём решения пользователя
                    if free is not None and free < 1:
                        labels = [b['label'] for b in buttons]
                        self._log("🐟 Садок заполнен — жду вашего решения...", "error")
                        choice = self._ask_sadok_full(message_text, labels)
                        if choice and choice != WAIT_SENTINEL:
                            self._log(f"Решение пользователя (садок): «{choice}»", "send")
                            vk.send_message(choice)
                        else:
                            self._log("⏳ Ждём следующего сообщения (садок).", "info")
                        continue

                    # Есть место в садке — авто-закидываем удочку
                    cast_btn = next(
                        (b['label'] for b in buttons
                         if "закинуть" in b['label'].lower() or "забросить" in b['label'].lower()),
                        None
                    )
                    if cast_btn:
                        self._log(f"🎣 Авто-рыбалка: «{cast_btn}»", "ai")
                        vk.send_message(cast_btn)
                        self._log(f"Отправлено: «{cast_btn}»", "send")
                        continue

                # Маслина выслеживает — ждём, ничего не нажимаем
                if buttons and ("маслина выследит" in message_text.lower()
                                or "выследит животное" in message_text.lower()):
                    self._log("🐕 Маслина выслеживает — ждём результата, «Вернуться» игнорируется.", "info")
                    continue

                # Маслина — авто-начало охоты
                if buttons and ("маслина" in message_text.lower()):
                    labels_map = {b['label'].lower().strip(): b['label'] for b in buttons}
                    hunt_btn = labels_map.get("начать охоту")
                    if hunt_btn:
                        self._log(f"🐾 Маслина — авто-старт: «{hunt_btn}»", "ai")
                        vk.send_message(hunt_btn)
                        self._log(f"Отправлено: «{hunt_btn}»", "send")
                        continue

                # Тёмный сталкер — авто-уходим без покупки
                if self._is_dark_stalker(message_text) and buttons:
                    labels_map = {b['label'].lower().strip(): b['label'] for b in buttons}
                    exit_btn = labels_map.get("уйти") or labels_map.get("⬅ уйти") or labels_map.get("отказаться")
                    if exit_btn:
                        self._log(f"👤 Тёмный сталкер — авто-уход: «{exit_btn}»", "ai")
                        vk.send_message(exit_btn)
                        self._log(f"Отправлено: «{exit_btn}»", "send")
                        continue

                # Схрон / машина / вертолёт — раскопка или обыск
                if buttons and self._is_stash_search(message_text, buttons):
                    if self.explore_stashes.get():
                        self._log("⛏ Обнаружен схрон/объект — ждём окончания раскопки...", "info")
                        continue
                    else:
                        cancel_btn = next(
                            (b['label'] for b in buttons
                             if b['label'].lower().strip() == "прервать"), None)
                        if cancel_btn:
                            self._log("⛏ Схроны отключены — прерываем: «Прервать»", "ai")
                            vk.send_message(cancel_btn)
                            self._log(f"Отправлено: «{cancel_btn}»", "send")
                            continue

                if buttons:
                    buttons = self._filter_buttons(buttons)
                    self.root.after(0, lambda b=list(buttons): self._update_quick_buttons(b))
                    labels = [b['label'] for b in buttons]
                    trader_action = self._choose_trader_action(message_text, buttons)
                    if trader_action:
                        action_low = trader_action.lower()
                        if any(kw in action_low for kw in self.TRADER_ALLOWED_KEYWORDS):
                            reason = "покупаем разрешённый товар"
                        elif any(kw in action_low for kw in self.TRADER_ASK_KEYWORDS):
                            reason = "спрашиваем ассортимент"
                        elif any(kw in action_low for kw in self.TRADER_ACCEPT_KEYWORDS):
                            reason = "подтверждаем покупку аптечек/болтов"
                        else:
                            reason = "отказываемся от лишнего товара"
                        self._log(f"Кнопки: {' | '.join(labels)}", "vk")
                        self._log(f"🛒 Торговец: {reason}: «{trader_action}»", "ai")
                        self._last_game_text = message_text
                        self._last_buttons = labels
                        self._last_choice = trader_action
                        self.root.after(0, lambda c=trader_action:
                                        self.last_decision_var.set(f"«{c}»"))
                        vk.send_message(trader_action)
                        self._log(f"Отправлено: «{trader_action}»", "send")
                        continue
                else:
                    self.root.after(0, lambda: self._update_quick_buttons([]))

                hp_info = self._parse_hp_info(message_text)
                if hp_info is not None:
                    h_cur, h_total = hp_info
                    hp_pct = round(h_cur / h_total * 100)
                    self._last_hp_pct = hp_pct
                    self.root.after(0, lambda c=h_cur, t=h_total, p=hp_pct:
                                    self.hp_display_var.set(f"{c}/{t} ({p}%)"))
                else:
                    hp_pct = self._last_hp_pct

                heal_thr = self.heal_threshold_var.get()
                eat_thr  = self.eat_threshold_var.get()
                rest_thr = self.rest_threshold_var.get()

                # HP выше порога отдыха — убираем "Отдохнуть" из вариантов
                if hp_pct is not None and hp_pct > rest_thr and len(buttons) > 1:
                    filtered = [b for b in buttons if "отдохнуть" not in b['label'].lower()]
                    if filtered:
                        self._log(
                            f"HP {hp_pct}% > {rest_thr}% — «Отдохнуть» исключена из вариантов", "info")
                        buttons = filtered

                # HP выше порога лечения — убираем аптечки
                if hp_pct is not None and hp_pct > heal_thr and len(buttons) > 1:
                    filtered = [b for b in buttons
                                if b['label'].lower().strip() not in self.MEDKIT_BUTTONS]
                    if filtered and len(filtered) < len(buttons):
                        self._log(
                            f"HP {hp_pct}% > {heal_thr}% — аптечки исключены из вариантов", "info")
                        buttons = filtered

                # Сытость выше порога — убираем кнопки еды из вариантов для ИИ
                hunger_data = self._parse_hunger(message_text)
                if hunger_data and len(buttons) > 1:
                    _hd_cur, _hd_max = hunger_data
                    _hd_pct = round(_hd_cur / _hd_max * 100) if _hd_max > 0 else 0
                    if _hd_pct > eat_thr:
                        food_keys = frozenset(self.FOOD_VALUES.keys())
                        filtered = [b for b in buttons
                                    if not any(k in b['label'].lower() for k in food_keys)]
                        if filtered and len(filtered) < len(buttons):
                            self._log(
                                f"🍞 Голод {_hd_cur}/{_hd_max} ({_hd_pct}%) > {eat_thr}% — "
                                f"сыт, еда исключена", "info")
                            buttons = filtered

                if buttons:
                    labels = [b['label'] for b in buttons]

                    # Авто-атака в бою при HP выше порога лечения — нажимаем первую кнопку атаки
                    if hp_pct is not None and hp_pct > heal_thr:
                        for priority in self.COMBAT_PRIORITY_BUTTONS:
                            for b in buttons:
                                if b['label'].lower().strip() == priority:
                                    self._log(f"HP {hp_pct}% — авто-атака: «{b['label']}»", "ai")
                                    self._last_game_text = message_text
                                    self._last_buttons = labels
                                    self._last_choice = b['label']
                                    self.root.after(0, lambda c=b['label']:
                                                    self.last_decision_var.set(f"«{c}»"))
                                    vk.send_message(b['label'])
                                    self._log(f"Отправлено: «{b['label']}»", "send")
                                    buttons = None
                                    break
                            if buttons is None:
                                break
                    if buttons is None:
                        continue
                    self._log(f"Кнопки: {' | '.join(labels)}", "vk")

                    # Кнопки-подтверждения — нажимаем автоматически
                    auto = self._auto_confirm_button(labels)
                    if auto:
                        self._log(f"Авто-подтверждение: «{auto}»", "info")
                        vk.send_message(auto)
                        continue

                    # Подменю аптечек — умный выбор по HP и наличию
                    if self._is_medkit_submenu(buttons):
                        anomaly_return = next(
                            (b['label'] for b in buttons
                             if "к аномалии" in b['label'].lower()),
                            None
                        )
                        combat_return = next(
                            (b['label'] for b in buttons
                             if "к бою" in b['label'].lower()),
                            None
                        )
                        if anomaly_return:
                            self._in_anomaly_heal = True
                        if combat_return:
                            self._in_combat_heal = True
                        # HP уже восстановлено — возвращаемся к контексту (аномалия/бой)
                        context_return = anomaly_return or combat_return
                        if context_return and hp_pct is not None and hp_pct > heal_thr:
                            self._in_anomaly_heal = False
                            self._in_combat_heal = False
                            self._log(
                                f"⚡ HP {hp_pct}% > {heal_thr}% — возвращаемся: «{context_return}»",
                                "ai",
                            )
                            vk.send_message(context_return)
                            self._log(f"Отправлено: «{context_return}»", "send")
                            continue
                        medkit = self._choose_medkit(buttons, hp_pct)
                        if medkit:
                            reason = f"HP {hp_pct}%" if hp_pct is not None else "HP неизвестен"
                            self._log(f"💊 Лечение: «{medkit}» ({reason})", "ai")
                            self._last_game_text = message_text
                            self._last_buttons = labels
                            self._last_choice = medkit
                            self.root.after(0, lambda c=medkit:
                                            self.last_decision_var.set(f"«{c}»"))
                            vk.send_message(medkit)
                            self._log(f"Отправлено: «{medkit}»", "send")
                        else:
                            self._log("💊 Аптечки закончились! Жду решения игрока...", "error")
                            self._user_choice = None
                            self._user_event.clear()
                            self.root.after(0, lambda t=message_text, b=labels:
                                            self._ask_user(t, b))
                            self._user_event.wait(timeout=300)
                            if self._user_choice and self._user_choice != WAIT_SENTINEL:
                                vk.send_message(self._user_choice)
                                self._log(f"Решение пользователя: «{self._user_choice}»", "send")
                        continue

                    hunger_info = self._parse_hunger(message_text) or self._last_hunger
                    hunger_pct = None
                    if hunger_info:
                        h_cur, h_max = hunger_info
                        hunger_pct = round(h_cur / h_max * 100) if h_max > 0 else 0

                    is_in_combat_now = any(
                        b['label'].lower().strip() in self.COMBAT_PRIORITY_BUTTONS
                        for b in buttons
                    )

                    # === Экран покупки еды у костра ===
                    if self._is_food_buy_screen(buttons):
                        self._last_buy_buttons = list(buttons)
                        if not self._buy_food_mode:
                            if hunger_info:
                                _hb_cur, _hb_max = hunger_info
                                self._buy_food_deficit = _hb_max - _hb_cur
                            else:
                                self._buy_food_deficit = 60
                            self._buy_food_mode = True
                            self._log(
                                f"🛒 Покупка еды: дефицит голода {self._buy_food_deficit} ед.", "info")

                        if self._buy_food_deficit <= 0:
                            back_btn = next(
                                (b['label'] for b in buttons
                                 if "назад" in b['label'].lower()), None)
                            if back_btn:
                                self._buy_food_mode = False
                                self._buy_food_deficit = 0
                                self._log("🛒 Еды куплено достаточно — возвращаемся", "ai")
                                vk.send_message(back_btn)
                                self._log(f"Отправлено: «{back_btn}»", "send")
                                continue
                        else:
                            buy_options = []
                            for b in buttons:
                                lbl_low = b['label'].lower()
                                for food_name, food_val in self.FOOD_VALUES.items():
                                    if food_name in lbl_low:
                                        buy_options.append((b['label'], food_val))
                                        break

                            if buy_options:
                                ok = [(lbl, val) for lbl, val in buy_options
                                      if val <= self._buy_food_deficit]
                                if ok:
                                    best_lbl, best_val = max(ok, key=lambda x: x[1])
                                else:
                                    best_lbl, best_val = min(buy_options, key=lambda x: x[1])

                                self._buy_food_deficit -= best_val
                                self._log(
                                    f"🛒 Покупаем «{best_lbl}» (+{best_val}), "
                                    f"осталось: {max(0, self._buy_food_deficit)} ед.", "ai")
                                vk.send_message(best_lbl)
                                self._log(f"Отправлено: «{best_lbl}»", "send")
                                continue
                            else:
                                back_btn = next(
                                    (b['label'] for b in buttons
                                     if "назад" in b['label'].lower()), None)
                                if back_btn:
                                    self._buy_food_mode = False
                                    self._buy_food_deficit = 0
                                    self._log("🛒 Нет доступной еды — выходим из магазина", "ai")
                                    vk.send_message(back_btn)
                                    self._log(f"Отправлено: «{back_btn}»", "send")
                                    continue

                    if hunger_info and hunger_pct is not None and hunger_pct <= eat_thr and not is_in_combat_now:
                        h_cur, h_max = hunger_info

                        if self._is_food_submenu(buttons):
                            food_btn = self._choose_food(buttons, h_cur, h_max)
                            if food_btn:
                                food_val = next(
                                    (v for k, v in self.FOOD_VALUES.items()
                                     if k in food_btn.lower()), 0)
                                self._log(
                                    f"🍞 Голод {h_cur}/{h_max} ({hunger_pct}%) ≤ {eat_thr}% — "
                                    f"едим «{food_btn}» (+{food_val})", "ai")
                                self._last_game_text = message_text
                                self._last_buttons = labels
                                self._last_choice = food_btn
                                self.root.after(0, lambda c=food_btn:
                                                self.last_decision_var.set(f"«{c}»"))
                                vk.send_message(food_btn)
                                self._log(f"Отправлено: «{food_btn}»", "send")
                                continue

                        snack_btn = next(
                            (b['label'] for b in buttons
                             if any(kw in b['label'].lower()
                                    for kw in ("перекус", "поесть", "покушать", "еда"))),
                            None
                        )
                        if snack_btn:
                            self._log(
                                f"🍞 Голод {h_cur}/{h_max} ({hunger_pct}%) ≤ {eat_thr}% — "
                                f"открываем еду: «{snack_btn}»", "ai")
                            vk.send_message(snack_btn)
                            self._log(f"Отправлено: «{snack_btn}»", "send")
                            continue

                        campfire_btn = next(
                            (b['label'] for b in buttons
                             if any(kw in b['label'].lower()
                                    for kw in ("к костру", "костёр", "костер"))),
                            None
                        )
                        if campfire_btn:
                            self._log(
                                f"🍞 Голод {h_cur}/{h_max} ({hunger_pct}%) ≤ {eat_thr}% — "
                                f"идём к костру: «{campfire_btn}»", "ai")
                            vk.send_message(campfire_btn)
                            self._log(f"Отправлено: «{campfire_btn}»", "send")
                            continue

                    # Еда у костра — умный выбор по уровню голода
                    if self._is_food_submenu(buttons):
                        if hunger_info:
                            h_cur, h_max = hunger_info
                            h_pct = round(h_cur / h_max * 100) if h_max > 0 else 0
                            if h_pct <= eat_thr:
                                food_btn = self._choose_food(buttons, h_cur, h_max)
                                if food_btn:
                                    food_val = next(
                                        (v for k, v in self.FOOD_VALUES.items()
                                         if k in food_btn.lower()), 0)
                                    deficit = h_max - h_cur
                                    self._log(
                                        f"🍞 Голод {h_cur}/{h_max} ({h_pct}%) ≤ {eat_thr}% — "
                                        f"едим «{food_btn}» (+{food_val})", "ai")
                                    self._last_game_text = message_text
                                    self._last_buttons = labels
                                    self._last_choice = food_btn
                                    self.root.after(0, lambda c=food_btn:
                                                    self.last_decision_var.set(f"«{c}»"))
                                    vk.send_message(food_btn)
                                    self._log(f"Отправлено: «{food_btn}»", "send")
                                    continue
                            else:
                                self._log(
                                    f"🍞 Голод {h_cur}/{h_max} ({h_pct}%) > {eat_thr}% — "
                                    f"сыт, ИИ решает что делать", "info")

                    # Обнаружена аномалия — войти или покинуть
                    enter_btn = next(
                        (b['label'] for b in buttons
                         if "рискнуть" in b['label'].lower() or "войти" in b['label'].lower()),
                        None
                    )
                    leave_btn = next(
                        (b['label'] for b in buttons
                         if "покинуть аномалию" in b['label'].lower()),
                        None
                    )
                    if enter_btn and leave_btn:
                        if self.explore_anomaly.get():
                            chosen = enter_btn
                            self._log(f"🌀 Аномалия — входим: «{chosen}»", "ai")
                        else:
                            chosen = leave_btn
                            self._log(f"🌀 Аномалия — пропускаем (исследование выкл.): «{chosen}»", "ai")
                        vk.send_message(chosen)
                        self._log(f"Отправлено: «{chosen}»", "send")
                        continue

                    # Аномалия — авто-бросок болта или лечение
                    if self._is_anomaly_active(message_text, buttons):
                        # Флаг "не исследовать аномалии" → отступаем
                        if not self.explore_anomaly.get():
                            retreat = next(
                                (b['label'] for b in buttons
                                 if "отступить" in b['label'].lower()),
                                None
                            )
                            if retreat:
                                self._log(f"⏭ Аномалия пропущена (исследование выкл.): «{retreat}»", "ai")
                                vk.send_message(retreat)
                                self._log(f"Отправлено: «{retreat}»", "send")
                                continue
                        hp_now = hp_pct if hp_pct is not None else 100
                        bolt_btn = next(
                            (b['label'] for b in buttons
                             if "кинуть болт" in b['label'].lower()
                             or "бросить болт" in b['label'].lower()),
                            None
                        )
                        heal_btn = next(
                            (b['label'] for b in buttons
                             if "лечение" in b['label'].lower()),
                            None
                        )
                        if hp_now <= heal_thr and heal_btn:
                            self._log(
                                f"🏥 Аномалия: HP {hp_now}% ≤ {heal_thr}% — лечимся «{heal_btn}»", "ai")
                            vk.send_message(heal_btn)
                            self._log(f"Отправлено: «{heal_btn}»", "send")
                            continue
                        elif bolt_btn:
                            self._log(f"⚡ Аномалия: бросаем болт (HP {hp_now}%)", "ai")
                            vk.send_message(bolt_btn)
                            self._log(f"Отправлено: «{bolt_btn}»", "send")
                            continue

                    # "К аномалии" — возврат после меню действий
                    return_anomaly_btn = next(
                        (b['label'] for b in buttons
                         if "к аномалии" in b['label'].lower()),
                        None
                    )
                    if return_anomaly_btn:
                        self._log(f"⚡ Возврат к аномалии: «{return_anomaly_btn}»", "ai")
                        vk.send_message(return_anomaly_btn)
                        self._log(f"Отправлено: «{return_anomaly_btn}»", "send")
                        continue

                    # Ящик/сундук — авто-выбор ключей или взлома
                    if self._is_chest_situation(message_text):
                        chest_choice = self._chest_auto_choice(message_text, buttons)
                        if chest_choice and not self._is_escape_button(chest_choice):
                            self._log(f"🔑 Найден ящик — авто-выбор: «{chest_choice}»", "ai")
                            self._last_game_text = message_text
                            self._last_buttons = labels
                            self._last_choice = chest_choice
                            self.root.after(0, lambda c=chest_choice:
                                            self.last_decision_var.set(f"«{c}»"))
                            vk.send_message(chest_choice)
                            self._log(f"Отправлено: «{chest_choice}»", "send")
                            continue

                    ai_game_text = message_text

                    # Авто-отдых при низком HP
                    if (hp_pct is not None and hp_pct <= rest_thr):
                        is_in_combat = any(
                            b['label'].lower().strip() in self.COMBAT_PRIORITY_BUTTONS
                            for b in buttons
                        )
                        # Идём отдыхать только если некуда применить себя:
                        # нет кнопки "Исследовать" ИЛИ HP упал ниже heal_thr (критически)
                        has_explore = any("исследовать" in b['label'].lower() for b in buttons)
                        truly_idle = not is_in_combat and (not has_explore or hp_pct <= heal_thr)
                        if truly_idle:
                            # Кнопка костра: "К костру", "Костёр", "🔥 Костёр" и т.п.
                            campfire_btn = next(
                                (b['label'] for b in buttons
                                 if any(kw in b['label'].lower()
                                        for kw in ("к костру", "костёр", "костер"))),
                                None
                            )
                            if campfire_btn:
                                self._log(
                                    f"🏕 HP {hp_pct}% ≤ {rest_thr}% — бездействие, "
                                    f"идём к костру: «{campfire_btn}»", "ai")
                                self._last_game_text = message_text
                                self._last_buttons = labels
                                self._last_choice = campfire_btn
                                self.root.after(0, lambda c=campfire_btn:
                                                self.last_decision_var.set(f"«{c}»"))
                                vk.send_message(campfire_btn)
                                self._log(f"Отправлено: «{campfire_btn}»", "send")
                                continue
                            rest_btn = next(
                                (b['label'] for b in buttons
                                 if "отдохнуть" in b['label'].lower()),
                                None
                            )
                            if rest_btn:
                                self._log(
                                    f"💤 HP {hp_pct}% ≤ {rest_thr}% — бездействие, "
                                    f"отдыхаем: «{rest_btn}»", "ai")
                                self._last_game_text = message_text
                                self._last_buttons = labels
                                self._last_choice = rest_btn
                                self.root.after(0, lambda c=rest_btn:
                                                self.last_decision_var.set(f"«{c}»"))
                                vk.send_message(rest_btn)
                                self._log(f"Отправлено: «{rest_btn}»", "send")
                                continue

                    # Авто-исследование: жмём "Исследовать" если HP в порядке или неизвестен
                    # (не спрашиваем ИИ — это всегда правильное действие в зоне)
                    if (hp_pct is None or hp_pct > heal_thr):
                        explore_btn = next(
                            (b['label'] for b in buttons
                             if "исследовать" in b['label'].lower()),
                            None
                        )
                        if explore_btn:
                            self._log(
                                f"🔍 Авто-исследование (HP {hp_pct}% > {heal_thr}%): "
                                f"«{explore_btn}»", "ai")
                            self._last_game_text = message_text
                            self._last_buttons = labels
                            self._last_choice = explore_btn
                            self.root.after(0, lambda c=explore_btn:
                                            self.last_decision_var.set(f"«{c}»"))
                            vk.send_message(explore_btn)
                            self._log(f"Отправлено: «{explore_btn}»", "send")
                            continue

                    # Режим пополнения болтов — навигация к Свалке и сбор ресурсов
                    if self._bolt_refilling:
                        cur_low = (self.nav.current_zone or "").lower().strip()
                        at_svалka = any(kw in cur_low for kw in ("свалка", "тропа на свалку"))
                        if not at_svалka:
                            nav_btns = self.nav.filter_backtrack(self.nav.movement_buttons(buttons))
                            move = self.nav.choose_move(nav_btns if nav_btns else buttons, "Свалка")
                            if move:
                                chosen, dir_key, method = move
                                if method == "bfs":
                                    path = self.nav.find_path("Свалка")
                                    self._log(f"🔩 → Свалка (граф): [{' → '.join(path)}] «{chosen}»", "ai")
                                else:
                                    hint = self.nav.compass_hint("Свалка")
                                    self._log(f"🔩 → Свалка (компас): {hint} «{chosen}»", "ai")
                                self.nav.record_moved(dir_key)
                                vk.send_message(chosen)
                                self._log(f"Отправлено: «{chosen}»", "send")
                                continue
                        else:
                            # На Свалке — ищем кнопку с болтами/ресурсами
                            bolt_btn = next(
                                (b['label'] for b in buttons
                                 if any(kw in b['label'].lower()
                                        for kw in ("болт", "ресурс", "пополн", "добыть"))),
                                None
                            )
                            if bolt_btn:
                                self._log(f"🔩 Свалка: берём ресурсы «{bolt_btn}»", "ai")
                                vk.send_message(bolt_btn)
                                self._log(f"Отправлено: «{bolt_btn}»", "send")
                                continue
                            # Специфической кнопки нет — исследуем зону в поисках болтов
                            expl = next(
                                (b['label'] for b in buttons
                                 if "исследовать" in b['label'].lower()),
                                None
                            )
                            if expl:
                                self._log(f"🔩 Свалка: исследуем в поиске болтов «{expl}»", "ai")
                                vk.send_message(expl)
                                self._log(f"Отправлено: «{expl}»", "send")
                                continue
                            # Иначе — ИИ решает что делать на Свалке

                    # Возврат в исходную зону после пополнения болтов
                    elif self._bolt_return_zone and not self._bolt_refilling:
                        cur_low = (self.nav.current_zone or "").lower().strip()
                        ret_low = self._bolt_return_zone.lower().strip()
                        if cur_low == ret_low:
                            self._log(
                                f"✅ Вернулись в «{self._bolt_return_zone}» — пополнение завершено",
                                "info",
                            )
                            self._bolt_return_zone = ""
                        else:
                            nav_btns = self.nav.filter_backtrack(self.nav.movement_buttons(buttons))
                            move = self.nav.choose_move(
                                nav_btns if nav_btns else buttons, self._bolt_return_zone)
                            if move:
                                chosen, dir_key, method = move
                                self._log(
                                    f"🏠 Возврат в «{self._bolt_return_zone}»: «{chosen}»", "ai")
                                self.nav.record_moved(dir_key)
                                vk.send_message(chosen)
                                self._log(f"Отправлено: «{chosen}»", "send")
                                continue

                    # Режим продажи рыбы — навигация в Деревню новичков и продажа
                    if self._fish_selling:
                        cur_low = (self.nav.current_zone or "").lower().strip()
                        at_village = "деревня новичков" in cur_low
                        if not at_village:
                            nav_btns = self.nav.filter_backtrack(self.nav.movement_buttons(buttons))
                            move = self.nav.choose_move(
                                nav_btns if nav_btns else buttons, "Деревня новичков")
                            if move:
                                chosen, dir_key, method = move
                                if method == "bfs":
                                    path = self.nav.find_path("Деревня новичков")
                                    self._log(
                                        f"🐟 → Деревня новичков (граф): [{' → '.join(path)}] «{chosen}»", "ai")
                                else:
                                    hint = self.nav.compass_hint("Деревня новичков")
                                    self._log(
                                        f"🐟 → Деревня новичков (компас): {hint} «{chosen}»", "ai")
                                self.nav.record_moved(dir_key)
                                vk.send_message(chosen)
                                self._log(f"Отправлено: «{chosen}»", "send")
                                continue
                        else:
                            # Приоритет 1: кнопки продажи рыбы по типу
                            sell_fish_btn = None
                            for kw in ("продать обычн", "продать средн", "продать трофей", "продать уникал"):
                                sell_fish_btn = next(
                                    (b['label'] for b in buttons if kw in b['label'].lower()), None)
                                if sell_fish_btn:
                                    break
                            if sell_fish_btn:
                                self._fish_sell_menu_entered = True
                                self._log(f"🐟 Продаём рыбу: «{sell_fish_btn}»", "ai")
                                vk.send_message(sell_fish_btn)
                                self._log(f"Отправлено: «{sell_fish_btn}»", "send")
                                continue
                            # Нет кнопок продажи конкретных рыб
                            if self._fish_sell_menu_entered:
                                # Уже входили в меню — значит вся рыба продана
                                self._fish_selling = False
                                self._fish_sell_menu_entered = False
                                self._log(
                                    f"✅ Рыба продана — возвращаемся в «{self._fish_return_zone}»",
                                    "info",
                                )
                            else:
                                # Приоритет 2: навигация к меню продажи
                                nav_sell_btn = None
                                for kw in ("продать рыб", "бестиарий рыб", "старик", "костёр", "костер"):
                                    nav_sell_btn = next(
                                        (b['label'] for b in buttons
                                         if kw in b['label'].lower()), None)
                                    if nav_sell_btn:
                                        break
                                if nav_sell_btn:
                                    self._log(f"🐟 Продажа → «{nav_sell_btn}»", "ai")
                                    vk.send_message(nav_sell_btn)
                                    self._log(f"Отправлено: «{nav_sell_btn}»", "send")
                                    continue

                    # Возврат в зону после продажи рыбы
                    if self._fish_return_zone and not self._fish_selling:
                        cur_low = (self.nav.current_zone or "").lower().strip()
                        ret_low = self._fish_return_zone.lower().strip()
                        if cur_low == ret_low:
                            self._log(
                                f"✅ Вернулись в «{self._fish_return_zone}» — продажа завершена",
                                "info",
                            )
                            self._fish_return_zone = ""
                        else:
                            nav_btns = self.nav.filter_backtrack(self.nav.movement_buttons(buttons))
                            move = self.nav.choose_move(
                                nav_btns if nav_btns else buttons, self._fish_return_zone)
                            if move:
                                chosen, dir_key, method = move
                                self._log(
                                    f"🏠 Возврат в «{self._fish_return_zone}»: «{chosen}»", "ai")
                                self.nav.record_moved(dir_key)
                                vk.send_message(chosen)
                                self._log(f"Отправлено: «{chosen}»", "send")
                                continue

                    choice, ai_log, confidence = self.ai_agent.decide(
                        ai_game_text, buttons, photo_url=photo_url)
                    self._log(ai_log, "ai")

                    # Низкая уверенность — спрашиваем пользователя
                    # В режиме навигации к цели — не спрашиваем, ИИ двигается сам
                    if confidence < CONFIDENCE_THRESHOLD:
                        self._log("⚠ ИИ не уверен — жду вашего решения...", "error")
                        self._user_choice = None
                        self._user_event.clear()
                        self.root.after(0, lambda t=message_text, b=labels:
                                        self._ask_user(t, b))
                        self._user_event.wait(timeout=120)
                        if self._user_choice:
                            choice = self._user_choice
                            if choice == WAIT_SENTINEL:
                                self._log("⏳ Ждём следующего сообщения.", "info")
                                continue
                            self._log(f"Решение пользователя: «{choice}»", "send")
                            self.ai_agent.add_feedback(
                                message_text, labels, choice, is_good=True)

                    # Обновляем панель оценки
                    self._last_game_text = message_text
                    self._last_buttons = labels
                    self._last_choice = choice
                    self.root.after(0, lambda c=choice:
                                    self.last_decision_var.set(f"«{c}»"))

                    # Побег — только с подтверждения пользователя
                    if self._is_escape_button(choice):
                        self._log(f"⚠ ИИ хочет «{choice}» — жду подтверждения...", "error")
                        choice = self._confirm_escape(choice, labels)
                        if choice == WAIT_SENTINEL:
                            self._log("⏳ Ждём следующего сообщения.", "info")
                            continue
                        self._log(f"Решение пользователя (побег): «{choice}»", "send")


                    vk.send_message(choice)
                    self._log(f"Отправлено: «{choice}»", "send")
                else:
                    if self._buy_food_mode and self._last_buy_buttons:
                        # Игра прислала подтверждение покупки без кнопок — продолжаем
                        if self._buy_food_deficit <= 0:
                            back_btn = next(
                                (b['label'] for b in self._last_buy_buttons
                                 if "назад" in b['label'].lower()), None)
                            if back_btn:
                                self._buy_food_mode = False
                                self._buy_food_deficit = 0
                                self._log("🛒 Еды куплено достаточно — возвращаемся", "ai")
                                vk.send_message(back_btn)
                                self._log(f"Отправлено: «{back_btn}»", "send")
                            else:
                                self._buy_food_mode = False
                        else:
                            buy_opts = []
                            for b in self._last_buy_buttons:
                                lbl_low = b['label'].lower()
                                for food_name, food_val in self.FOOD_VALUES.items():
                                    if food_name in lbl_low:
                                        buy_opts.append((b['label'], food_val))
                                        break
                            if buy_opts:
                                ok = [(lbl, val) for lbl, val in buy_opts
                                      if val <= self._buy_food_deficit]
                                if ok:
                                    best_lbl, best_val = max(ok, key=lambda x: x[1])
                                else:
                                    best_lbl, best_val = min(buy_opts, key=lambda x: x[1])
                                self._buy_food_deficit -= best_val
                                self._log(
                                    f"🛒 Покупаем ещё «{best_lbl}» (+{best_val}), "
                                    f"осталось: {max(0, self._buy_food_deficit)} ед.", "ai")
                                vk.send_message(best_lbl)
                                self._log(f"Отправлено: «{best_lbl}»", "send")
                            else:
                                back_btn = next(
                                    (b['label'] for b in self._last_buy_buttons
                                     if "назад" in b['label'].lower()), None)
                                if back_btn:
                                    self._buy_food_mode = False
                                    self._buy_food_deficit = 0
                                    vk.send_message(back_btn)
                                    self._log(f"Отправлено: «{back_btn}»", "send")
                    elif self._in_anomaly_heal or self._in_combat_heal:
                        # Игра не прислала новые кнопки после лечения — проверяем HP
                        hp_after = self._parse_hp_percent(message_text)
                        heal_thr_now = self.heal_threshold_var.get()
                        if hp_after is not None and hp_after > heal_thr_now:
                            if self._in_anomaly_heal:
                                self._in_anomaly_heal = False
                                return_label = "К аномалии"
                            else:
                                self._in_combat_heal = False
                                return_label = "К бою"
                            self._log(
                                f"⚡ После лечения HP {hp_after}% > {heal_thr_now}% — «{return_label}»",
                                "ai",
                            )
                            vk.send_message(return_label)
                            self._log(f"Отправлено: «{return_label}»", "send")
                        else:
                            self._log(
                                f"⏳ Кнопок нет, HP {hp_after}% — ждём продолжения лечения.",
                                "info",
                            )
                    else:
                        self._log("Кнопок нет — ждём следующего сообщения.", "info")

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self._log(f"Критическая ошибка: {e}", "error")
            for line in tb.splitlines():
                self._log(line, "error")
            self.root.after(0, self._stop)
        finally:
            self._vk_client = None


if __name__ == "__main__":
    root = tk.Tk()
    try:
        root.iconbitmap(default='')
    except Exception:
        pass
    app = App(root)
    root.mainloop()
