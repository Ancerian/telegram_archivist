#!/usr/bin/env python3
"""
gui.py — Графічний інтерфейс Telegram Archivist.
Темна тема, вибір моделей, підтримка LM Studio.
"""

import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext
import threading
import time
import sys
import io
import os
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()


# ─── Палітра ───────────────────────────────────────────────

BG           = "#0f172a"
BG_CARD      = "#1e293b"
BG_INPUT     = "#020617"
BG_BUTTON    = "#6366f1"
BG_BUTTON_H  = "#818cf8"
BG_STOP      = "#ef4444"
FG           = "#f8fafc"
FG_DIM       = "#94a3b8"
FG_ACCENT    = "#c7d2fe"
FG_OK        = "#4ade80"
FG_WARN      = "#fbbf24"
FG_ERR       = "#f87171"
BORDER       = "#334155"
FONT         = ("SF Pro Display", 13)
FONT_BOLD    = ("SF Pro Display", 13, "bold")
FONT_TITLE   = ("SF Pro Display", 24, "bold")
FONT_H2      = ("SF Pro Display", 16, "bold")
FONT_MONO    = ("SF Mono", 12)
FONT_SM      = ("SF Pro Display", 11)


# ─── Пресети моделей ───────────────────────────────────────

PROVIDER_MODELS = {
    "Google Gemini": [
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite-preview-02-05",
        "gemini-1.5-pro",
        "gemini-1.5-flash",
        "gemini-1.5-flash-8b",
        "gemini-2.0-pro-exp-02-05",
    ],
    "Gemini Full Context (1M)": [
        "gemini-1.5-pro",
        "gemini-1.5-flash",
        "gemini-2.0-flash",
    ],
    "Anthropic Claude": [
        "claude-3-5-sonnet-20241022",
        "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229",
        "claude-3-sonnet-20240229",
        "claude-3-haiku-20240307",
    ],
    "OpenAI": [
        "o1-preview",
        "o1-mini",
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-3.5-turbo",
    ],
    "LM Studio (локальна)": [
        "local-model",
    ],
}

PROVIDER_MAP = {
    "Google Gemini": "google",
    "Gemini Full Context (1M)": "google_full",
    "Anthropic Claude": "anthropic",
    "OpenAI": "openai",
    "LM Studio (локальна)": "local",
}

ENV_KEYS = {
    "Google Gemini": "GOOGLE_API_KEY",
    "Gemini Full Context (1M)": "GOOGLE_API_KEY",
    "Anthropic Claude": "ANTHROPIC_API_KEY",
    "OpenAI": "OPENAI_API_KEY",
}


class ArchivistGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("🗄 Telegram Archivist")
        self.root.configure(bg=BG)
        self.root.minsize(1000, 600)
        self.root.geometry("1200x780")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._running = False
        self._thread = None
        self._start_time = None
        self._timer_id = None
        self._wait_event = None
        self._log_filter = "all"  # all, ok, warn, err
        self._settings_file = Path.home() / ".telegram_archivist_settings.json"

        self._build_style()
        self._build_ui()
        self._on_provider_change()
        self._load_settings()

    # ─── Стиль ──────────────────────────────────────────────

    def _build_style(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(".", background=BG, foreground=FG, font=FONT,
                         borderwidth=0, focuscolor=BG_BUTTON)
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=BG_CARD)
        style.configure("TLabel", background=BG, foreground=FG, font=FONT)
        style.configure("Card.TLabel", background=BG_CARD, foreground=FG)
        style.configure("Dim.TLabel", background=BG_CARD, foreground=FG_DIM, font=FONT_SM)
        style.configure("H2.TLabel", background=BG, foreground=FG_ACCENT, font=FONT_H2)
        style.configure("Title.TLabel", background=BG, foreground=FG, font=FONT_TITLE)

        style.configure("TEntry", fieldbackground=BG_INPUT, foreground=FG,
                         insertcolor=FG, borderwidth=0, relief="flat", padding=8)
        style.map("TEntry", fieldbackground=[("focus", BG_INPUT)])

        style.configure("TCombobox", fieldbackground=BG_INPUT, background=BG_INPUT,
                         foreground=FG, arrowcolor=FG_DIM, borderwidth=0,
                         relief="flat", padding=6)
        style.map("TCombobox",
                   fieldbackground=[("readonly", BG_INPUT)],
                   selectbackground=[("readonly", BG_INPUT)],
                   selectforeground=[("readonly", FG)])

        style.configure("Accent.TButton", background=BG_BUTTON, foreground="#ffffff",
                         font=FONT_BOLD, padding=(24, 12), borderwidth=0)
        style.map("Accent.TButton",
                   background=[("active", BG_BUTTON_H), ("disabled", BORDER)])

        style.configure("Stop.TButton", background=BG_STOP, foreground="#ffffff",
                         font=FONT_BOLD, padding=(24, 12), borderwidth=0)
        style.map("Stop.TButton",
                   background=[("active", "#f87171")])

        style.configure("Browse.TButton", background=BG_INPUT, foreground=FG_ACCENT,
                         font=FONT_SM, padding=(8, 4), borderwidth=0)
        style.map("Browse.TButton",
                   background=[("active", BORDER)])

        style.configure("TCheckbutton", background=BG_CARD, foreground=FG, font=FONT)
        style.map("TCheckbutton", 
                   background=[("active", BG_CARD)],
                   foreground=[("active", FG)])

        style.configure("Custom.Horizontal.TProgressbar",
                         troughcolor=BG_INPUT, background=BG_BUTTON,
                         borderwidth=0, lightcolor=BG_BUTTON,
                         darkcolor=BG_BUTTON)
        style.configure("Pct.TLabel", background=BG, foreground=FG_ACCENT,
                         font=("SF Mono", 13, "bold"))

    # ─── UI ─────────────────────────────────────────────────

    def _build_ui(self):
        # Заголовок
        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=24, pady=(15, 5))
        ttk.Label(header, text="🗄  Telegram Archivist", style="Title.TLabel").pack(side="left")

        # Головний контейнер (горизонтальний)
        main_container = ttk.Frame(self.root)
        main_container.pack(fill="both", expand=True, padx=24, pady=(0, 15))

        # --- Ліва колонка: Налаштування ---
        left_col = ttk.Frame(main_container)
        left_col.pack(side="left", fill="both", expand=False, padx=(0, 10))

        # Контейнер для скрол-зони (щоб відділити від кнопок знизу)
        settings_area = ttk.Frame(left_col, width=580)
        settings_area.pack(side="top", fill="both", expand=True)
        settings_area.pack_propagate(False) # Тут фіксуємо ширину тільки для зони скролу

        # Scrollable Canvas для налаштувань
        self.canvas = tk.Canvas(settings_area, bg=BG, highlightthickness=0, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(settings_area, orient="vertical", command=self.canvas.yview)
        self.settings_container = ttk.Frame(self.canvas)

        self.settings_container.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas_window = self.canvas.create_window((0, 0), window=self.settings_container, anchor="nw", width=560)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        # Mousewheel scroll
        def _on_mousewheel(event):
            self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        self.canvas.bind_all("<MouseWheel>", _on_mousewheel)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        # Внутрішній контейнер для секцій налаштувань
        settings_scroll = self.settings_container

        # ── Карточка: Шляхи ──
        self._section(settings_scroll, "📂  Шляхи")
        card_paths = self._card(settings_scroll)
        self.input_var = tk.StringVar(value=str(Path.home() / "Downloads"))
        self._path_row(card_paths, "Експорт Telegram", self.input_var, 0)
        self.vault_var = tk.StringVar(value=str(Path.home() / "Documents" / "Obsidian Vault"))
        self._path_row(card_paths, "Obsidian Vault", self.vault_var, 1)

        # ── Карточка: LLM ──
        self._section(settings_scroll, "🧠  LLM Провайдер")
        card_llm = self._card(settings_scroll)

        # Провайдер
        r = 0
        ttk.Label(card_llm, text="Провайдер", style="Card.TLabel").grid(row=r, column=0, sticky="w", padx=8, pady=4)
        self.provider_var = tk.StringVar(value="Google Gemini")
        self.provider_combo = ttk.Combobox(card_llm, textvariable=self.provider_var, values=list(PROVIDER_MODELS.keys()), state="readonly", width=30)
        self.provider_combo.grid(row=r, column=1, sticky="ew", padx=8, pady=4)
        self.provider_combo.bind("<<ComboboxSelected>>", lambda e: self._on_provider_change())

        # Модель
        r = 1
        ttk.Label(card_llm, text="Модель", style="Card.TLabel").grid(row=r, column=0, sticky="w", padx=8, pady=4)
        self.model_var = tk.StringVar()
        self.model_combo = ttk.Combobox(card_llm, textvariable=self.model_var, values=[], width=30)
        self.model_combo.grid(row=r, column=1, sticky="ew", padx=8, pady=4)

        # API Key
        r = 2
        self.key_label = ttk.Label(card_llm, text="API Key", style="Card.TLabel")
        self.key_label.grid(row=r, column=0, sticky="w", padx=8, pady=4)
        self.key_var = tk.StringVar()
        self.key_entry = ttk.Entry(card_llm, textvariable=self.key_var, show="•", width=38)
        self.key_entry.grid(row=r, column=1, sticky="ew", padx=8, pady=4)

        # LM Studio URL
        r = 3
        self.url_label = ttk.Label(card_llm, text="LM Studio URL", style="Card.TLabel")
        self.url_var = tk.StringVar(value="http://localhost:1234/v1")
        self.url_entry = ttk.Entry(card_llm, textvariable=self.url_var, width=38)
        self.url_label.grid(row=r, column=0, sticky="w", padx=8, pady=4)
        self.url_entry.grid(row=r, column=1, sticky="ew", padx=8, pady=4)

        # LM Studio Context Size
        r = 4
        self.context_label = ttk.Label(card_llm, text="Контекст моделі", style="Card.TLabel")
        self.context_var = tk.StringVar(value="12K")
        self.context_map = {
            "4K": 4096, "8K": 8192, "12K": 12000, 
            "32K": 32768, "40K": 40960, "64K": 65536, "128K": 131072
        }
        self.context_combo = ttk.Combobox(card_llm, textvariable=self.context_var, values=list(self.context_map.keys()), state="readonly", width=15)
        self.context_combo.bind("<<ComboboxSelected>>", lambda e: self._update_effective_context())
        self.context_label.grid(row=r, column=0, sticky="w", padx=8, pady=4)
        self.context_combo.grid(row=r, column=1, sticky="w", padx=8, pady=4)

        # Двоетапний аналіз (CoT)
        r = 5
        self.cot_var = tk.BooleanVar(value=False)
        self.cot_check = ttk.Checkbutton(card_llm, text="🧠 Двоетапний аналіз (CoT)", variable=self.cot_var)
        self.cot_check.grid(row=r, column=0, columnspan=2, sticky="w", padx=8, pady=2)
        ttk.Label(card_llm, text="└ Покращує якість для локальних моделей", style="Dim.TLabel").grid(row=r+1, column=0, columnspan=2, sticky="w", padx=28, pady=(0, 4))

        # Паралельність
        r = 7
        self.parallel_label = ttk.Label(card_llm, text="Паралельність", style="Card.TLabel")
        self.parallel_label.grid(row=r, column=0, sticky="w", padx=8, pady=4)
        parallel_frame = ttk.Frame(card_llm, style="Card.TFrame")
        parallel_frame.grid(row=r, column=1, sticky="ew", padx=8, pady=4)
        self.parallel_var = tk.IntVar(value=4)
        def _on_scale(val):
            v = int(float(val))
            self.parallel_val_label.configure(text=f"{v} потоків")
            self.parallel_var.set(v)
            self._update_effective_context()
        self.parallel_scale = ttk.Scale(parallel_frame, from_=1, to=16, variable=self.parallel_var, orient="horizontal", command=_on_scale)
        self.parallel_scale.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.parallel_val_label = ttk.Label(parallel_frame, text="4 потоків", style="Dim.TLabel", width=10)
        self.parallel_val_label.pack(side="left")
        self.btn_auto_parallel = ttk.Button(parallel_frame, text="🔍 Авто", style="Browse.TButton", command=self._on_auto_parallel)
        self.btn_auto_parallel.pack(side="left", padx=(5, 0))

        # Ефективний контекст
        r = 8
        self.effective_label = ttk.Label(card_llm, text="", style="Dim.TLabel")
        self.effective_label.grid(row=r, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 2))

        # Підказка
        r = 9
        self.hint_label = ttk.Label(card_llm, text="", style="Dim.TLabel", wraplength=450)
        self.hint_label.grid(row=r, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 4))
        card_llm.columnconfigure(1, weight=1)

        # ── Карточка: Транскрипція ──
        self._section(settings_scroll, "🎙  Транскрипція")
        card_trans = self._card(settings_scroll)
        self.transcribe_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(card_trans, text="Транскрибувати голосові та кружки", variable=self.transcribe_var, command=self._on_transcribe_toggle).grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=4)
        ttk.Label(card_trans, text="Whisper модель", style="Card.TLabel").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        self.whisper_var = tk.StringVar(value="small")
        self.whisper_combo = ttk.Combobox(card_trans, textvariable=self.whisper_var, values=["tiny", "small", "medium"], state="readonly", width=15)
        self.whisper_combo.grid(row=1, column=1, sticky="w", padx=8, pady=4)
        self.twophase_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(card_trans, text="🔄 Двофазний режим ( RAM cleanup )", variable=self.twophase_var).grid(row=2, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 4))

        # ── Карточка: Післяобробка ──
        self._section(settings_scroll, "⚙️  Післяобробка")
        card_post = self._card(settings_scroll)
        self.graph_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(card_post, text="🕸️ Генерувати граф зв'язків", variable=self.graph_var).grid(row=0, column=0, columnspan=2, sticky="w", padx=8, pady=4)
        self.dedupe_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(card_post, text="🔍 Дедуплікувати після аналізу", variable=self.dedupe_var).grid(row=1, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 4))

        # ── Керування та прогрес ──
        ctrl_frame = ttk.Frame(left_col)
        ctrl_frame.pack(fill="x", side="bottom", pady=(5, 0))

        btn_frame = ttk.Frame(ctrl_frame)
        btn_frame.pack(fill="x", pady=(0, 2))
        self.start_btn = ttk.Button(btn_frame, text="▶  Запустити", style="Accent.TButton", command=self._start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(btn_frame, text="⏹  Зупинити", style="Stop.TButton", command=self._stop)
        self.stop_btn.pack(side="left", padx=(10, 0))
        self.stop_btn.state(["disabled"])

        self.status_label = ttk.Label(btn_frame, text="Готовий", foreground=FG_DIM, font=FONT_SM)
        self.status_label.pack(side="right")

        prog_frame = ttk.Frame(ctrl_frame)
        prog_frame.pack(fill="x", pady=(0, 2))
        self.progress_var = tk.DoubleVar(value=0)
        self.progressbar = ttk.Progressbar(prog_frame, variable=self.progress_var, maximum=100, mode="determinate", style="Custom.Horizontal.TProgressbar")
        self.progressbar.pack(side="left", fill="x", expand=True)
        self.pct_label = ttk.Label(prog_frame, text="0 %", style="Pct.TLabel", width=6)
        self.pct_label.pack(side="right", padx=(8, 0))

        timer_frame = ttk.Frame(ctrl_frame)
        timer_frame.pack(fill="x")
        self.elapsed_label = ttk.Label(timer_frame, text="⏱ 00:00", foreground=FG_DIM, font=FONT_SM)
        self.elapsed_label.pack(side="left")
        self.eta_label = ttk.Label(timer_frame, text="", foreground=FG_DIM, font=FONT_SM)
        self.eta_label.pack(side="right")


        # --- Права колонка: Лог ---
        log_pane = ttk.Frame(main_container)
        log_pane.pack(side="right", fill="both", expand=True, padx=(20, 0))
        
        # Заголовок + фільтри
        log_header = ttk.Frame(log_pane)
        log_header.pack(fill="x")
        self._section(log_header, "📜  Лог подій")
        
        filter_frame = ttk.Frame(log_header)
        filter_frame.pack(side="right", padx=8, pady=(14, 2))
        for label, ftype in [("Всі", "all"), ("✅", "ok"), ("⚠️", "warn"), ("❌", "err")]:
            btn = ttk.Button(filter_frame, text=label, style="Browse.TButton",
                             command=lambda f=ftype: self._apply_log_filter(f))
            btn.pack(side="left", padx=2)

        self.log = scrolledtext.ScrolledText(
            log_pane, wrap="word",
            bg="#020617", fg=FG, insertbackground=FG,
            font=FONT_MONO, relief="flat", borderwidth=0,
            highlightthickness=1, highlightbackground=BORDER,
            state="disabled", padx=10, pady=10
        )
        self.log.pack(fill="both", expand=True)

        # Теги для лога
        self.log.tag_config("ok", foreground=FG_OK)
        self.log.tag_config("warn", foreground=FG_WARN)
        self.log.tag_config("err", foreground=FG_ERR)
        self.log.tag_config("accent", foreground=FG_ACCENT)

        # Кнопки утиліт під логом
        util_frame = ttk.Frame(log_pane)
        util_frame.pack(fill="x", pady=(4, 0))
        ttk.Button(util_frame, text="🏥 Health Check", style="Browse.TButton",
                   command=self._run_health_check).pack(side="left", padx=4)
        ttk.Button(util_frame, text="📂 Відкрити Vault", style="Browse.TButton",
                   command=self._open_vault).pack(side="left", padx=4)

    # ─── Хелпери UI ─────────────────────────────────────────

    def _section(self, parent, text):
        ttk.Label(parent, text=text, style="H2.TLabel").pack(
            anchor="w", padx=4, pady=(14, 2))

    def _card(self, parent) -> ttk.Frame:
        card = ttk.Frame(parent, style="Card.TFrame", padding=10)
        card.pack(fill="x", pady=(0, 2))
        return card

    def _path_row(self, parent, label, var, row):
        ttk.Label(parent, text=label, style="Card.TLabel").grid(
            row=row, column=0, sticky="w", padx=8, pady=4)
        entry = ttk.Entry(parent, textvariable=var, width=40)
        entry.grid(row=row, column=1, sticky="ew", padx=8, pady=4)
        ttk.Button(parent, text="Огляд…", style="Browse.TButton",
                    command=lambda: self._browse(var)).grid(
            row=row, column=2, padx=(0, 8), pady=4)
        parent.columnconfigure(1, weight=1)

    def _browse(self, var):
        path = filedialog.askdirectory(initialdir=var.get() or "~")
        if path:
            var.set(path)

    # ─── Логіка провайдера ──────────────────────────────────

    def _update_effective_context(self):
        provider_name = self.provider_var.get()
        if provider_name == "LM Studio (локальна)":
            context_str = self.context_var.get()
            context_size = self.context_map.get(context_str, 12000)
            parallel = max(1, self.parallel_var.get())
            effective = (context_size // parallel) - 1500
            if effective < 1000:
                self.effective_label.configure(text=f"⚠️ Занадто мало токенів на батч (~{effective})! Зменш паралельність або збільш контекст.", foreground=FG_ERR)
            else:
                self.effective_label.configure(text=f"⚡ Ефективний контекст на батч: ~{effective} токенів", foreground=FG_ACCENT)
        else:
            self.effective_label.configure(text="")

    def _on_provider_change(self):
        provider_name = self.provider_var.get()
        models = PROVIDER_MODELS.get(provider_name, [])
        is_local = (provider_name == "LM Studio (локальна)")

        # Моделі
        self.model_combo["values"] = models
        if is_local:
            self.model_combo["state"] = "normal"
            self.model_var.set("")
            self._try_load_lm_studio_models()
        elif models:
            self.model_combo["state"] = "readonly"
            self.model_var.set(models[0])
        else:
            self.model_combo["state"] = "normal"
            self.model_var.set("")

        # API key
        if is_local:
            self.key_entry.state(["disabled"])
            self.key_var.set("")
            self.key_label.configure(foreground=FG_DIM)
            self.url_label.grid()
            self.url_entry.grid()
            self.context_label.grid()
            self.context_combo.grid()
            self.btn_auto_parallel.state(["!disabled"])
            self.hint_label.configure(
                text="💡 Увага: Значення 'Контекст моделі' тут має збігатися з налаштуванням Context Length у самій LM Studio! Натисніть 'Авто' для визначення потоків.")
            self._update_effective_context()
        else:
            self.key_entry.state(["!disabled"])
            self.key_label.configure(foreground=FG)
            self.url_label.grid_remove()
            self.url_entry.grid_remove()
            self.context_label.grid_remove()
            self.context_combo.grid_remove()
            self.btn_auto_parallel.state(["disabled"])
            env = ENV_KEYS.get(provider_name, "")
            env_val = os.environ.get(env, "")
            if env_val and not self.key_var.get():
                self.key_var.set(env_val)
            self.hint_label.configure(
                text=f"💡 Або встановіть змінну середовища {env}. Для хмарних: не більше 5." if env else "💡 Для хмарних: рекомендована паралельність не більше 5.")
            self._update_effective_context()

    def _on_auto_parallel(self):
        from analyzer import EntityAnalyzer
        import threading
        
        self.btn_auto_parallel.state(["disabled"])
        self.btn_auto_parallel.config(text="⏳ ...")
        
        def _detect():
            dummy = EntityAnalyzer(provider="local", api_key="", chat_name="", chat_language="", local_url=self.url_var.get())
            val = dummy.detect_max_concurrent()
            
            def _update_ui():
                self.parallel_var.set(val)
                self.parallel_val_label.configure(text=f"{val} потоків")
                self.parallel_scale.set(val)
                self.btn_auto_parallel.configure(text="🔍 Авто")
                self.btn_auto_parallel.state(["!disabled"])
                if val == 1:
                    self._log_write(
                        "⚠️ LM Studio не розкриває кількість паралельних слотів через API. "
                        "Встановіть значення вручну відповідно до параметра 'Parallel' у LM Studio.", "warn")
                else:
                    self._log_write(f"🔧 Авто-визначення: {val} паралельних запитів", "ok")
                
            self.root.after(0, _update_ui)
            
        threading.Thread(target=_detect, daemon=True).start()

    def _try_load_lm_studio_models(self):
        """Спробувати отримати список моделей з LM Studio."""
        def fetch():
            try:
                import openai
                client = openai.OpenAI(
                    base_url=self.url_var.get(),
                    api_key="lm-studio",
                )
                models_response = client.models.list()
                names = [m.id for m in models_response.data]
                if names:
                    self.root.after(0, lambda: self._set_lm_models(names))
            except Exception:
                pass

        threading.Thread(target=fetch, daemon=True).start()

    def _set_lm_models(self, names):
        self.model_combo["values"] = names
        if names and not self.model_var.get():
            self.model_var.set(names[0])
        self.hint_label.configure(text=f"✅ Знайдено {len(names)} модель(ей) в LM Studio")

    def _on_transcribe_toggle(self):
        if self.transcribe_var.get():
            self.whisper_combo.state(["!disabled"])
        else:
            self.whisper_combo.state(["disabled"])

    # ─── Запуск ─────────────────────────────────────────────

    def _log_write(self, text, tag=None):
        """Безпечний запис у лог з головного потоку з фільтрацією."""
        # Зберігаємо всі записи для replay при зміні фільтра
        if not hasattr(self, '_log_entries'):
            self._log_entries = []
        self._log_entries.append((text, tag))

        # Перевіряємо фільтр
        if self._log_filter != "all" and tag and tag != self._log_filter:
            return

        def _write():
            self.log.configure(state="normal")
            if tag:
                self.log.insert("end", text + "\n", tag)
            else:
                self.log.insert("end", text + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.root.after(0, _write)

    def _apply_log_filter(self, filter_type: str):
        """Застосовує фільтр до логу (all/ok/warn/err)."""
        self._log_filter = filter_type
        # Перемалювуємо лог
        def _rewrite():
            self.log.configure(state="normal")
            self.log.delete("1.0", "end")
            for text, tag in getattr(self, '_log_entries', []):
                if filter_type == "all" or not tag or tag == filter_type:
                    if tag:
                        self.log.insert("end", text + "\n", tag)
                    else:
                        self.log.insert("end", text + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.root.after(0, _rewrite)

    def _set_status(self, text, color=FG_DIM):
        self.root.after(0, lambda: self.status_label.configure(text=text, foreground=color))

    def _set_progress(self, value):
        """Встановлює прогрес 0-100 і оновлює ETA."""
        value = max(0, min(100, value))
        def _update():
            self.progress_var.set(value)
            self.pct_label.configure(text=f"{int(value)} %")
        self.root.after(0, _update)

    def _format_time(self, seconds):
        """Форматує секунди в MM:SS або HH:MM:SS."""
        seconds = int(seconds)
        if seconds < 3600:
            return f"{seconds // 60:02d}:{seconds % 60:02d}"
        return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"

    def _tick_timer(self):
        """Оновлює таймер щосекунди."""
        if not self._running or self._start_time is None:
            return

        elapsed = time.time() - self._start_time
        self.elapsed_label.configure(text=f"⏱ {self._format_time(elapsed)}")

        if getattr(self, '_llm_start_time', None) is not None and getattr(self, '_llm_session_total_batches', 0) > 0:
            if getattr(self, '_llm_session_batches_done', 0) > 0:
                elapsed_llm = time.time() - self._llm_start_time
                avg_time = elapsed_llm / self._llm_session_batches_done
                remaining_batches = self._llm_session_total_batches - self._llm_session_batches_done
                if remaining_batches < 0: remaining_batches = 0
                eta = remaining_batches * avg_time
                self.eta_label.configure(text=f"≈ {self._format_time(eta)} залишилось (по швидкості LLM)")
            else:
                self.eta_label.configure(text="вимірювання швидкості LLM...")
        else:
            pct = self.progress_var.get()
            if pct > 2:
                eta = elapsed / pct * (100 - pct)
                self.eta_label.configure(text=f"≈ {self._format_time(eta)} залишилось")
            else:
                self.eta_label.configure(text="розрахунок...")

        self._timer_id = self.root.after(1000, self._tick_timer)

    def _stop_timer(self):
        """Зупиняє таймер."""
        if self._timer_id is not None:
            self.root.after_cancel(self._timer_id)
            self._timer_id = None

    def _on_close(self):
        """Очищення та вихід при закритті вікна."""
        self._running = False
        if self._wait_event:
            self._wait_event.set()
        self.root.destroy()
        import sys
        sys.exit(0)

    def _start(self):
        self._save_settings()
        # Валідація
        input_path = Path(self.input_var.get().strip())
        vault_path = Path(self.vault_var.get().strip())
        provider_name = self.provider_var.get()
        provider = PROVIDER_MAP.get(provider_name, "google")
        model = self.model_var.get().strip() or None
        api_key = self.key_var.get().strip()
        local_url = self.url_var.get().strip()
        do_transcribe = self.transcribe_var.get()
        whisper_model = self.whisper_var.get()
        generate_graph = self.graph_var.get()
        dedupe_vault = self.dedupe_var.get()

        if not input_path.exists():
            self._log_write(f"❌ Папка експорту не знайдена: {input_path}", "err")
            return
        if not (input_path / "result.json").exists():
            self._log_write(f"❌ result.json не знайдено у {input_path}", "err")
            return
        if provider != "local" and not api_key:
            self._log_write(f"❌ Введіть API ключ для {provider_name}", "err")
            return
        if provider == "local" and not model:
            self._log_write("❌ Вкажіть назву моделі для LM Studio", "err")
            return

        effective_max_tokens = 16000
        absolute_max_tokens = 32000
        if provider == "local":
            context_str = self.context_var.get()
            context_size = self.context_map.get(context_str, 12000)
            parallel = max(1, self.parallel_var.get())
            effective_max_tokens = (context_size // parallel) - 1500
            absolute_max_tokens = context_size - 1500

        # Блокуємо UI
        self.start_btn.state(["disabled"])
        self.stop_btn.state(["!disabled"])
        self._running = True
        self._start_time = time.time()
        self._set_progress(0)
        self.elapsed_label.configure(text="⏱ 00:00")
        self.eta_label.configure(text="розрахунок...")
        self._tick_timer()

        # Очищаємо лог
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

        self._log_write(f"🚀 Запуск аналізу...", "accent")
        self._log_write(f"   Провайдер: {provider_name}  |  Модель: {model or 'default'}")
        self._log_write(f"   Експорт: {input_path}")
        self._log_write(f"   Vault: {vault_path}")
        self._log_write("")

        self._thread = threading.Thread(target=self._run_pipeline, daemon=True,
            kwargs=dict(
                input_path=input_path,
                vault_path=vault_path,
                provider=provider,
                model=model,
                api_key=api_key,
                local_url=local_url,
                do_transcribe=do_transcribe,
                whisper_model=whisper_model,
                twophase=self.twophase_var.get(),
                max_concurrent=self.parallel_var.get, # Передаємо функцію get для динамічності
                max_tokens=effective_max_tokens,
                absolute_max_tokens=absolute_max_tokens,
                use_cot=self.cot_var.get(),
                generate_graph=generate_graph,
                dedupe_vault=dedupe_vault,
            ))
        self._thread.start()

    def _stop(self):
        self._running = False
        if self._wait_event:
            self._wait_event.set()
        self._stop_timer()
        self._log_write("\n⏹ Зупинка...", "warn")
        self._set_status("Зупинено", FG_WARN)
        self.start_btn.state(["!disabled"])
        self.stop_btn.state(["disabled"])

    def _show_twophase_dialog(self, event):
        dialog = tk.Toplevel(self.root)
        dialog.title("Очікування LLM")
        dialog.configure(bg=BG)
        
        ttk.Label(dialog, text="🎙 Транскрипція завершена", font=FONT_TITLE, background=BG, foreground=FG_ACCENT).pack(padx=20, pady=(20, 5))
        ttk.Label(dialog, text="Whisper вивантажено з пам'яті.", font=FONT, background=BG, foreground=FG).pack(padx=20, pady=2)
        ttk.Label(dialog, text="Будь ласка, запустіть вашу LLM (наприклад, у LM Studio).\nПісля цього натисніть «Продовжити».", justify="center", font=FONT, background=BG, foreground=FG_DIM).pack(padx=20, pady=10)
        
        def _on_continue():
            dialog.destroy()
            event.set()
            
        ttk.Button(dialog, text="▶ Продовжити аналіз", style="Accent.TButton", command=_on_continue).pack(pady=20)
        
        # Центрування
        self.root.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 200
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 100
        dialog.geometry(f"+{x}+{y}")
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Обробка закриття вікна хрестиком
        def _on_close():
            self._stop()
            dialog.destroy()
            event.set()
        dialog.protocol("WM_DELETE_WINDOW", _on_close)

    def _run_pipeline(self, *, input_path, vault_path, provider, model,
                       api_key, local_url, do_transcribe, whisper_model, twophase, max_concurrent, max_tokens, use_cot,
                       generate_graph, dedupe_vault, absolute_max_tokens=128000):
        """Основний пайплайн у фоновому потоці."""
        try:
            # Додаємо шлях до проєкту
            project_dir = str(Path(__file__).parent)
            if project_dir not in sys.path:
                sys.path.insert(0, project_dir)

            from registry import IdentityRegistry
            from parser import TelegramParser
            from transcriber import LocalTranscriber
            from analyzer import EntityAnalyzer
            from merger import EntityMerger
            from writer import ObsidianWriter
            from deduplicator import VaultDeduplicator

            if not self._running:
                return

            # Розрахунок загальної вартості (cost) для чесного ETA
            parser = TelegramParser()
            parser.load(input_path)
            all_messages = parser.get_messages()
            checkpoint_path = input_path / "llm_checkpoint.json"
            last_processed = EntityAnalyzer.get_last_processed_date(checkpoint_path)
            messages_for_cost = parser.get_new_messages(last_processed) if last_processed else all_messages

            media_count = 0
            if do_transcribe:
                media_count = sum(1 for m in messages_for_cost if m.get("media_type") in ("voice_message", "video_message") and m.get("file_path") is not None)

            batch_size = 50
            total_batches = max(1, (len(messages_for_cost) + batch_size - 1) // batch_size)

            COST_INIT = 10
            COST_PARSE = 10
            COST_TRANS = media_count * 50
            COST_LLM = total_batches * 100
            COST_WRITE = 20
            COST_DEDUPE = 20 if dedupe_vault else 0

            TOTAL_COST = COST_INIT + COST_PARSE + COST_TRANS + COST_LLM + COST_WRITE + COST_DEDUPE
            current_cost = 0

            def _add_cost(amount):
                nonlocal current_cost
                current_cost += amount
                self._set_progress((current_cost / TOTAL_COST) * 100)

            # 1. Реєстр
            _add_cost(COST_INIT)
            self._set_status("[1/6] Завантаження реєстру…", FG_ACCENT)
            self._log_write("[1/6] Завантаження реєстру...", "accent")
            registry = IdentityRegistry(vault_path)
            registry.load()
            self._log_write(f"  ✅ Реєстр завантажено", "ok")
            self._set_progress(5)

            if not self._running:
                return

            # 2. Парсинг
            _add_cost(COST_PARSE)
            self._set_status("[2/6] Парсинг експорту…", FG_ACCENT)
            self._log_write("\n[2/6] Парсинг експорту...", "accent")
            parser = TelegramParser()
            parser.load(input_path)
            all_messages = parser.get_messages()
            messages = all_messages
            chat_name = parser.get_chat_name()
            chat_language = parser.get_chat_language()
            self._log_write(f"  📋 Чат: {chat_name}")
            self._log_write(f"  📝 Повідомлень: {len(all_messages)}, мова: {chat_language}")
            checkpoint_path = input_path / "llm_checkpoint.json"
            last_processed = EntityAnalyzer.get_last_processed_date(checkpoint_path)
            if last_processed:
                messages = parser.get_new_messages(last_processed)
                self._log_write(f"  🔄 Знайдено {len(messages)} нових повідомлень", "accent")
            self._set_progress(15)

            if not self._running:
                return

            # 3. Транскрипція
            if do_transcribe:
                self._set_status(f"[3/6] Транскрипція ({media_count} файлів)…", FG_ACCENT)
                self._log_write(f"\n[3/6] Транскрипція голосових та кружків... ({media_count} файлів)", "accent")
                if media_count > 0:

                    def _whisper_progress(done, total, filename, lang, from_cache):
                        if not self._running:
                            return
                        _add_cost(50)
                        if from_cache:
                            if done % 10 == 0 or done == total:
                                self._set_status(f"[3/6] Транскрипція {done}/{total} (з кешу)", FG_ACCENT)
                        else:
                            lang_str = f" (мова: {lang})" if lang else ""
                            self._log_write(f"  ✅ Файл {done}/{total}: {filename}{lang_str}", "ok")
                            self._set_status(f"[3/6] Транскрипція {done}/{total}", FG_ACCENT)

                    transcriber = LocalTranscriber(model_size=whisper_model)
                    messages = transcriber.transcribe_batch(messages, input_path=input_path, progress_callback=_whisper_progress)
                    self._log_write(f"  ✅ Транскрипція завершена ({media_count} файлів)", "ok")

                    # Двофазний режим: вивантажити Whisper з RAM
                    if twophase:
                        self._log_write("  🧹 Вивантаження Whisper з RAM...", "warn")
                        transcriber.unload()
                        del transcriber
                        self._log_write("  ✅ RAM звільнено. Очікування підтвердження користувача...", "accent")
                        self._set_status("[3/6] Очікування запуску LLM...", FG_WARN)
                        
                        self._wait_event = threading.Event()
                        self.root.after(0, lambda: self._show_twophase_dialog(self._wait_event))
                        self._wait_event.wait()
                        self._wait_event = None
                        
                        if not self._running:
                            return
                        
                        self._log_write("  ▶ Продовження роботи...", "ok")
                else:
                    self._log_write("  ℹ️ Немає медіафайлів для транскрипції")
            else:
                self._log_write("\n[3/6] Транскрипція пропущена", "warn")

            if not self._running:
                return

            # 4. Аналіз LLM
            self._set_status(f"[4/6] Аналіз через LLM…", FG_ACCENT)
            self._log_write(f"\n[4/6] Аналіз через {provider} ({model or 'default'})...", "accent")
            known_entities = registry.get_all_names()

            self._llm_start_time = time.time()
            self._llm_session_batches_done = 0
            self._llm_session_total_batches = total_batches

            def _llm_progress(msg):
                import re as _re
                
                # Віднімаємо батчі, якщо вони вже виконані та завантажені з чекпоінту
                if "Відновлено прогрес:" in msg:
                    m = _re.search(r"Відновлено прогрес: (\d+)/", msg)
                    if m:
                        self._llm_session_total_batches = total_batches - int(m.group(1))

                # Рахуємо реально виконані у цій сесії батчі
                if "оброблено успішно" in msg or "не повернув корисних даних" in msg or "Критична помилка у батчі" in msg:
                    self._llm_session_batches_done += 1

                # Додаємо cost лише для TOP-рівневих батчів (не рекурсивних, не повторних спроб)
                # Топ-рівневі батчі мають відступ рівно 2 пробіли (depth=0),
                # вкладені (split) — 4+ пробіли.
                is_top_level_batch = (
                    msg.startswith("  📊") and
                    not msg.startswith("    📊") and
                    "(спроба" not in msg
                )
                stripped = msg.lstrip()
                if is_top_level_batch:
                    _add_cost(100)
                    # Витягуємо номер батчу для статусрядка
                    try:
                        import re as _re
                        m = _re.search(r"📊 Батч (\d+)/(\d+)", stripped)
                        if m:
                            self._set_status(f"[4/6] Батч {m.group(1)}/{m.group(2)}", FG_ACCENT)
                    except Exception:
                        self._set_status(f"[4/6] Аналіз LLM...", FG_ACCENT)
                
                # Визначаємо тег для лога
                tag = None
                if "✅" in msg: tag = "ok"
                elif "⚠️" in msg: tag = "warn"
                elif "❌" in msg: tag = "err"
                
                self._log_write(msg, tag)

            analyzer = EntityAnalyzer(
                provider=provider,
                api_key=api_key,
                chat_name=chat_name,
                chat_language=chat_language,
                model=model,
                local_url=local_url,
                progress_callback=_llm_progress,
                max_concurrent=max_concurrent,
                is_running_callback=lambda: self._running,
                max_tokens=max_tokens,
                absolute_max_tokens=absolute_max_tokens,
                use_cot=use_cot,
            )
            if provider == "google_full":
                analyzed_entities = analyzer.analyze_full_context(messages, known_entities, checkpoint_path=checkpoint_path)
            else:
                analyzed_entities = analyzer.analyze(messages, known_entities, checkpoint_path=checkpoint_path)
            summary_messages = analyzer.last_analyzed_messages or messages
            summary_text = analyzer.generate_chat_summary(summary_messages, analyzed_entities)
            if summary_text:
                self._log_write("  📝 Summary чату згенеровано", "ok")
            self._log_write("  ✅ Аналіз завершено", "ok")
            self._set_progress(90)

            if not self._running:
                return

            # Вимикаємо динамічний таймер LLM після 4-го етапу
            self._llm_start_time = None

            # 5. Запис
            _add_cost(COST_WRITE)
            self._set_status("[5/6] Запис у vault…", FG_ACCENT)
            self._log_write(f"\n[5/6] Запис у vault...", "accent")
            merger = EntityMerger(registry)
            merge_report = merger.merge(analyzed_entities, chat_name)

            writer = ObsidianWriter(vault_path, registry=registry)
            stats = writer.write_all(merge_report, chat_name)
            writer.write_chat_index(chat_name, all_messages, analyzed_entities, chat_language)
            if summary_text:
                writer.write_chat_summary(chat_name, summary_messages, summary_text)
                self._log_write("  📝 Summary чату збережено", "ok")
            if generate_graph:
                graph_path = writer.write_graph_canvas()
                if graph_path:
                    self._log_write(f"  🕸️ Граф зв'язків: {graph_path}", "ok")
            registry.save()

            # 6. Дедуплікація
            if dedupe_vault:
                _add_cost(COST_DEDUPE)
                self._set_status("[6/6] Дедуплікація vault…", FG_ACCENT)
                self._log_write(f"\n[6/6] Дедуплікація vault...", "accent")
                deduplicator = VaultDeduplicator()
                duplicate_groups = deduplicator.find_duplicates(vault_path)
                merged_count = deduplicator.merge_duplicates(duplicate_groups, registry)
                registry.save()
                if generate_graph:
                    writer.write_graph_canvas()
                self._log_write(f"  🔍 Знайдено {len(duplicate_groups)} груп дублікатів, злито {merged_count} файлів", "ok")
            else:
                self._log_write(f"\n[6/6] Дедуплікація пропущена", "warn")

            # Статистика
            created = stats.get("created", {})
            updated = stats.get("updated", {})
            skipped = stats.get("skipped", {})
            successful = {
                key: created.get(key, 0) + updated.get(key, 0)
                for key in ("people", "projects", "events", "themes")
            }
            self._log_write("")
            self._log_write("═" * 50, "ok")
            self._log_write("✅ Готово!", "ok")
            self._log_write(f"   Мова чату: {chat_language}")
            self._log_write("📊 Статистика запису:", "accent")
            self._log_write(
                f"   ✅ Успішно: {successful.get('people', 0)} людей, "
                f"{successful.get('projects', 0)} проєктів, "
                f"{successful.get('events', 0)} подій, "
                f"{successful.get('themes', 0)} тем", "ok")
            self._log_write(
                f"   🔄 Оновлено: {updated.get('people', 0)} людей, "
                f"{updated.get('projects', 0)} проєктів, "
                f"{updated.get('events', 0)} подій, "
                f"{updated.get('themes', 0)} тем")
            self._log_write(
                f"   ⚠️ Пропущено (без імені): {skipped.get('total', 0)} сутностей",
                "warn" if skipped.get("total", 0) else None)
            self._log_write(
                f"   📎 Entity links: {stats.get('entity_links', 0)} посилань створено")
            self._log_write(f"   Vault: {vault_path}")
            self._log_write("═" * 50, "ok")

            self._set_status("✅ 100 % — Готово!", FG_OK)
            self._notify_completion(success=True)

            # Фіксуємо фінальний час
            elapsed = time.time() - self._start_time
            self.root.after(0, lambda: self.elapsed_label.configure(
                text=f"⏱ {self._format_time(elapsed)} — завершено"))
            self.root.after(0, lambda: self.eta_label.configure(text=""))

        except Exception as e:
            self._log_write(f"\n❌ Критична помилка: {e}", "err")
            import traceback
            self._log_write(traceback.format_exc(), "err")
            self._set_status("❌ Помилка", FG_ERR)
            self._notify_completion(success=False)

        finally:
            self._running = False
            self._stop_timer()
            self.root.after(0, lambda: self.start_btn.state(["!disabled"]))
            self.root.after(0, lambda: self.stop_btn.state(["disabled"]))

    # ─── Settings Persistence (6.2) ─────────────────────────

    def _save_settings(self):
        """Зберігає налаштування в JSON файл."""
        import json
        try:
            settings = {
                "input_path": self.input_var.get() if hasattr(self, 'input_var') else "",
                "vault_path": self.vault_var.get() if hasattr(self, 'vault_var') else "",
                "provider": self.provider_var.get() if hasattr(self, 'provider_var') else "",
                "model": self.model_var.get() if hasattr(self, 'model_var') else "",
                "max_tokens": self.tokens_var.get() if hasattr(self, 'tokens_var') else "128000",
                "concurrency": self.concurrent_var.get() if hasattr(self, 'concurrent_var') else "3",
            }
            with open(self._settings_file, "w", encoding="utf-8") as f:
                json.dump(settings, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_settings(self):
        """Завантажує збережені налаштування."""
        import json
        try:
            if not self._settings_file.exists():
                return
            with open(self._settings_file, "r", encoding="utf-8") as f:
                settings = json.load(f)
            if settings.get("input_path") and hasattr(self, 'input_var'):
                self.input_var.set(settings["input_path"])
            if settings.get("vault_path") and hasattr(self, 'vault_var'):
                self.vault_var.set(settings["vault_path"])
            if settings.get("provider") and hasattr(self, 'provider_var'):
                self.provider_var.set(settings["provider"])
                self._on_provider_change()
            if settings.get("model") and hasattr(self, 'model_var'):
                self.model_var.set(settings["model"])
            if settings.get("max_tokens") and hasattr(self, 'tokens_var'):
                self.tokens_var.set(settings["max_tokens"])
            if settings.get("concurrency") and hasattr(self, 'concurrent_var'):
                self.concurrent_var.set(settings["concurrency"])
        except Exception:
            pass

    # ─── Health Check (17) ──────────────────────────────────

    def _run_health_check(self):
        """Запускає перевірку системи і виводить результати в лог."""
        from health_check import SystemHealthCheck
        self._log_write("\n🏥 Перевірка системи...\n", "accent")
        checker = SystemHealthCheck()
        config = {
            "provider": PROVIDER_MAP.get(self.provider_var.get(), ""),
            "local_url": self.local_url_var.get() if hasattr(self, 'local_url_var') else "",
            "vault_path": self.vault_var.get() if hasattr(self, 'vault_var') else "",
            "input_path": self.input_var.get() if hasattr(self, 'input_var') else "",
        }
        results = checker.run_all(config)
        all_ok = True
        for r in results:
            icon = "✅" if r["ok"] else ("❌" if r.get("critical") else "⚠️")
            tag = "ok" if r["ok"] else ("err" if r.get("critical") else "warn")
            self._log_write(f"  {icon} {r['name']}: {r['detail']}", tag)
            if not r["ok"]:
                all_ok = False
        if all_ok:
            self._log_write("\n✅ Всі перевірки пройдені!", "ok")
        else:
            self._log_write("\n⚠️ Є проблеми, перевірте вище.", "warn")

    # ─── Open Vault (6.4) ──────────────────────────────────

    def _open_vault(self):
        """Відкриває vault у файловому менеджері."""
        vault_path = self.vault_var.get() if hasattr(self, 'vault_var') else ""
        if not vault_path or not Path(vault_path).exists():
            self._log_write("⚠️ Vault не знайдено", "warn")
            return
        import subprocess
        try:
            subprocess.Popen(["open", vault_path])
        except Exception as e:
            self._log_write(f"⚠️ Не вдалося відкрити: {e}", "warn")

    # ─── Notification (6.3) ─────────────────────────────────

    def _notify_completion(self, success: bool = True):
        """Нотифікація про завершення через macOS AppleScript."""
        try:
            import subprocess
            title = "✅ Аналіз завершено" if success else "❌ Аналіз не вдався"
            msg = "Telegram Archivist завершив обробку."
            subprocess.run([
                "osascript", "-e",
                f'display notification "{msg}" with title "{title}" sound name "Glass"'
            ], capture_output=True, timeout=5)
        except Exception:
            pass

    # ─── Запуск ─────────────────────────────────────────────

    def run(self):
        self.root.mainloop()


def main():
    app = ArchivistGUI()
    app.run()


if __name__ == "__main__":
    main()
