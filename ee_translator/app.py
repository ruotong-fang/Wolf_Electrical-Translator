import os
from pathlib import Path
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .documents import DocumentError, extract_document, text_candidates
from .engine import (
    ArgosBackend,
    TranslationPipeline,
    TranslationResult,
    TranslationUnavailable,
    install_argos_package,
    install_bundled_packages,
)
from .paths import app_data_dir, bundled_llm_dir, bundled_models_dir, configure_offline_environment
from .polishing import LocalLlamaPolisher
from .preferences import AppPreferences
from .terminology import (
    TERM_CATEGORIES,
    Term,
    TerminologyStore,
    TranslationMemory,
    parameter_signature,
    segment_text,
)


class TranslatorApp(tk.Tk):
    BG = "#09111f"
    SURFACE = "#101c2e"
    SURFACE_ALT = "#16253b"
    BORDER = "#28405d"
    NAVY = "#dcecff"
    ACCENT = "#25c8d9"
    ACCENT_DARK = "#123e50"
    MUTED = "#829bb5"
    TEXT = "#dcecff"
    SUCCESS = "#44d69a"

    def __init__(self):
        super().__init__()
        configure_offline_environment()
        self.title("电气工程翻译器")
        self.geometry("1180x780")
        self.minsize(940, 650)
        self.configure(background=self.BG)

        data_dir = app_data_dir()
        self.store = TerminologyStore(data_dir / "terminology.db")
        self.preferences_path = data_dir / "preferences.json"
        self.preferences = AppPreferences.load(self.preferences_path)
        if self.preferences.context_size < 8192:
            self.preferences.context_size = 8192
        model_name = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
        model_candidates = (data_dir / "llm" / model_name, bundled_llm_dir() / model_name)
        default_model = next((path for path in model_candidates if path.is_file()), None)
        if (not self.preferences.model_path or not os.path.isfile(self.preferences.model_path)) and default_model:
            self.preferences.model_path = str(default_model)
            self.preferences.save(self.preferences_path)
        self.polisher = self._make_polisher()
        self.backend = ArgosBackend()
        self.pipeline = TranslationPipeline(self.backend, self.polisher)

        self.direction = tk.StringVar(value="en-zh")
        self.mode = tk.StringVar(value="快速翻译")
        self.status = tk.StringVar(value="正在检查本地翻译引擎...")
        self.opened_file = tk.StringVar(value="未打开文件，可直接粘贴文字")
        self.model_path = tk.StringVar(value=self.preferences.model_path)
        self.model_status = tk.StringVar(value=self.polisher.status())
        self.term_category = tk.StringVar(value=TERM_CATEGORIES[0])
        self.term_domain = tk.StringVar(value="通用")
        self.term_priority = tk.StringVar(value="100")
        self.translating = False
        self.last_source = ""
        self.last_result = ""
        self.memory_hint = ""

        self._configure_styles()
        self._build_ui()
        self._refresh_terms()
        self._refresh_memories()
        self.after(100, self._initialize_engine)

    def _make_polisher(self) -> LocalLlamaPolisher:
        return LocalLlamaPolisher(
            self.preferences.model_path,
            self.preferences.context_size,
            self.preferences.model_threads,
        )

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=self.BG)
        style.configure("Card.TFrame", background=self.SURFACE)
        style.configure("TLabel", background=self.BG, foreground=self.TEXT, font=("Microsoft YaHei UI", 10))
        style.configure("Card.TLabel", background=self.SURFACE, foreground=self.TEXT)
        style.configure("Muted.TLabel", background=self.BG, foreground=self.MUTED)
        style.configure("Title.TLabel", background=self.SURFACE, foreground=self.TEXT, font=("Microsoft YaHei UI", 19, "bold"))
        style.configure("Subtitle.TLabel", background=self.SURFACE, foreground=self.ACCENT)
        style.configure("Accent.TButton", background=self.ACCENT, foreground="#04131c", bordercolor=self.ACCENT, padding=(16, 8), font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#63e4ee"), ("disabled", "#31515f")], foreground=[("disabled", "#8297a5")])
        style.configure("TButton", background=self.SURFACE_ALT, foreground=self.TEXT, bordercolor=self.BORDER, lightcolor=self.BORDER, darkcolor=self.BORDER, padding=(10, 7))
        style.map("TButton", background=[("active", "#203754"), ("pressed", self.ACCENT_DARK)])
        style.configure("TEntry", fieldbackground=self.SURFACE_ALT, foreground=self.TEXT, insertcolor=self.ACCENT, bordercolor=self.BORDER, lightcolor=self.BORDER, darkcolor=self.BORDER, padding=7)
        style.configure("TCombobox", fieldbackground=self.SURFACE_ALT, background=self.SURFACE_ALT, foreground=self.TEXT, arrowcolor=self.ACCENT, bordercolor=self.BORDER, padding=5)
        style.map("TCombobox", fieldbackground=[("readonly", self.SURFACE_ALT)], foreground=[("readonly", self.TEXT)], selectbackground=[("readonly", self.SURFACE_ALT)], selectforeground=[("readonly", self.TEXT)])
        style.configure("TRadiobutton", background=self.BG, foreground=self.TEXT, indicatorcolor=self.SURFACE_ALT, padding=4)
        style.map("TRadiobutton", background=[("active", self.BG)], indicatorcolor=[("selected", self.ACCENT)])
        style.configure("TNotebook", background=self.BG, borderwidth=0)
        style.configure("TNotebook.Tab", padding=(16, 9), background=self.SURFACE_ALT, foreground=self.TEXT, font=("Microsoft YaHei UI", 10))
        style.configure("TLabelframe", background=self.SURFACE, bordercolor=self.BORDER, relief="solid", borderwidth=1)
        style.configure("TLabelframe.Label", background=self.BG, foreground=self.ACCENT, font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Treeview", background=self.SURFACE, fieldbackground=self.SURFACE, foreground=self.TEXT, bordercolor=self.BORDER, rowheight=30, font=("Microsoft YaHei UI", 9))
        style.map("Treeview", background=[("selected", self.ACCENT_DARK)], foreground=[("selected", "#effcff")])
        style.configure("Treeview.Heading", background=self.SURFACE_ALT, foreground=self.ACCENT, bordercolor=self.BORDER, relief="flat", font=("Microsoft YaHei UI", 9, "bold"))
        style.map("Treeview.Heading", background=[("active", "#203754")])

    def _build_ui(self) -> None:
        header = ttk.Frame(self, padding=(22, 14), style="Card.TFrame")
        navy = tk.Frame(header, bg=self.SURFACE, height=76, highlightbackground=self.BORDER, highlightthickness=1)
        navy.pack(fill="x")
        navy.pack_propagate(False)
        tk.Frame(navy, bg=self.ACCENT, width=4).pack(side="left", fill="y")
        title_group = tk.Frame(navy, bg=self.SURFACE)
        title_group.pack(side="left", padx=18, pady=9)
        ttk.Label(title_group, text="EE // TRANSLATOR", style="Subtitle.TLabel").pack(anchor="w")
        ttk.Label(title_group, text="电气工程翻译器", style="Title.TLabel").pack(anchor="w")
        tk.Label(
            navy,
            text="  LOCAL  ·  OFFLINE  ",
            bg=self.ACCENT_DARK,
            fg=self.ACCENT,
            font=("Consolas", 10, "bold"),
            padx=10,
            pady=7,
        ).pack(side="right", padx=20)
        header.pack(fill="x")

        nav = tk.Frame(self, bg=self.SURFACE, height=50, highlightbackground=self.BORDER, highlightthickness=1)
        nav.pack(fill="x", padx=22)
        nav.pack_propagate(False)
        content = ttk.Frame(self)
        content.pack(fill="both", expand=True, padx=22, pady=(0, 10))
        tabs = [ttk.Frame(content, padding=14) for _ in range(4)]
        self.main_tabs = tabs
        self.nav_buttons = []
        for index, title in enumerate(("翻译", "术语与短语", "翻译记忆", "本地设置")):
            button = tk.Button(
                nav,
                text=title,
                command=lambda selected=index: self._show_main_tab(selected),
                relief="flat",
                borderwidth=0,
                font=("Microsoft YaHei UI", 10, "bold"),
                cursor="hand2",
            )
            button.pack(side="left", fill="both", expand=True)
            self.nav_buttons.append(button)
        self._build_translate_tab(tabs[0])
        self._build_terms_tab(tabs[1])
        self._build_memory_tab(tabs[2])
        self._build_settings_tab(tabs[3])
        self._show_main_tab(0)

        status_bar = ttk.Frame(self, padding=(22, 8))
        status_bar.pack(fill="x")
        ttk.Label(status_bar, text="●", foreground=self.SUCCESS).pack(side="left")
        ttk.Label(status_bar, textvariable=self.status, style="Muted.TLabel").pack(side="left", padx=7)

    def _show_main_tab(self, selected: int) -> None:
        for index, (tab, button) in enumerate(zip(self.main_tabs, self.nav_buttons)):
            tab.pack_forget()
            active = index == selected
            button.configure(
                bg=self.ACCENT_DARK if active else self.SURFACE,
                fg=self.ACCENT if active else self.MUTED,
                activebackground="#174b5d" if active else self.SURFACE_ALT,
                activeforeground=self.ACCENT if active else self.TEXT,
                highlightbackground=self.ACCENT if active else self.SURFACE,
                highlightthickness=2 if active else 0,
            )
        self.main_tabs[selected].pack(fill="both", expand=True)

    def _make_text_widget(self, parent, *, undo: bool = False) -> tk.Text:
        return tk.Text(
            parent,
            wrap="word",
            undo=undo,
            font=("Microsoft YaHei UI", 11),
            bg=self.SURFACE_ALT,
            fg=self.TEXT,
            insertbackground=self.ACCENT,
            selectbackground=self.ACCENT_DARK,
            selectforeground="#effcff",
            relief="flat",
            highlightbackground=self.BORDER,
            highlightcolor=self.ACCENT,
            highlightthickness=1,
            padx=12,
            pady=12,
        )

    def _show_result_view(self, selected: int) -> None:
        for index, (view, button) in enumerate(zip(self.result_views, self.result_buttons)):
            view.pack_forget()
            active = index == selected
            button.configure(
                bg=self.ACCENT_DARK if active else self.SURFACE,
                fg=self.ACCENT if active else self.MUTED,
                activebackground="#174b5d" if active else self.SURFACE_ALT,
                activeforeground=self.ACCENT if active else self.TEXT,
                highlightbackground=self.ACCENT if active else self.SURFACE,
                highlightthickness=2 if active else 0,
            )
        self.result_views[selected].pack(fill="both", expand=True)

    def _build_translate_tab(self, parent: ttk.Frame) -> None:
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill="x", pady=(0, 10))
        ttk.Button(toolbar, text="打开文件", command=self._open_file).pack(side="left")
        ttk.Label(toolbar, textvariable=self.opened_file, style="Muted.TLabel").pack(side="left", padx=10)

        controls = ttk.Frame(parent)
        controls.pack(fill="x", pady=(0, 10))
        ttk.Radiobutton(controls, text="英文 → 中文", variable=self.direction, value="en-zh").pack(side="left")
        ttk.Radiobutton(controls, text="中文 → 英文", variable=self.direction, value="zh-en").pack(side="left", padx=12)
        ttk.Label(controls, text="翻译模式：").pack(side="left", padx=(22, 5))
        ttk.Combobox(controls, textvariable=self.mode, values=("快速翻译", "专业翻译"), state="readonly", width=12).pack(side="left")
        self.translate_button = ttk.Button(controls, text="开始翻译", command=self._translate, style="Accent.TButton")
        self.translate_button.pack(side="right")
        ttk.Button(controls, text="保存译文", command=self._save_translation).pack(side="right", padx=7)
        ttk.Button(controls, text="记住此译文", command=self._remember_translation).pack(side="right")
        ttk.Button(controls, text="清空", command=self._clear_text).pack(side="right", padx=7)

        panes = tk.PanedWindow(
            parent,
            orient="horizontal",
            bg=self.BORDER,
            sashwidth=6,
            sashrelief="flat",
            borderwidth=0,
            relief="flat",
            showhandle=False,
        )
        panes.pack(fill="both", expand=True)
        left = ttk.Labelframe(panes, text="原文", padding=9)
        right = ttk.Labelframe(panes, text="译文", padding=9)
        panes.add(left, stretch="always", minsize=340)
        panes.add(right, stretch="always", minsize=340)
        self.source_text = self._make_text_widget(left, undo=True)
        self.source_text.pack(fill="both", expand=True)
        result_switcher = tk.Frame(right, bg=self.SURFACE, height=42, highlightbackground=self.BORDER, highlightthickness=1)
        result_switcher.pack(fill="x", pady=(0, 8))
        result_switcher.pack_propagate(False)
        self.result_buttons = []
        for index, title in enumerate(("最终译文", "ARGOS 初译")):
            button = tk.Button(
                result_switcher,
                text=title,
                command=lambda selected=index: self._show_result_view(selected),
                relief="flat",
                borderwidth=0,
                font=("Microsoft YaHei UI", 9, "bold"),
                cursor="hand2",
            )
            button.pack(side="left", fill="both", expand=True)
            self.result_buttons.append(button)
        result_body = tk.Frame(right, bg=self.SURFACE)
        result_body.pack(fill="both", expand=True)
        final_frame = tk.Frame(result_body, bg=self.SURFACE)
        draft_frame = tk.Frame(result_body, bg=self.SURFACE)
        self.result_views = [final_frame, draft_frame]
        self.target_text = self._make_text_widget(final_frame, undo=True)
        self.draft_text = self._make_text_widget(draft_frame)
        self.target_text.pack(fill="both", expand=True)
        self.draft_text.pack(fill="both", expand=True)
        self._show_result_view(0)

    def _build_terms_tab(self, parent: ttk.Frame) -> None:
        form = ttk.Labelframe(parent, text="添加专业表达", padding=12)
        form.pack(fill="x", pady=(0, 10))
        self.english_entry = ttk.Entry(form)
        self.chinese_entry = ttk.Entry(form)
        self.note_entry = ttk.Entry(form)
        domains = ("通用", "电力系统", "开关与保护", "继电保护", "变压器与电机", "电机控制", "电缆与接地", "建筑电气", "图纸与CAD", "试验与调试", "工程表达")
        widgets = (("英文", self.english_entry, 2), ("中文", self.chinese_entry, 2), ("类型", ttk.Combobox(form, textvariable=self.term_category, values=TERM_CATEGORIES, state="readonly", width=10), 1), ("领域", ttk.Combobox(form, textvariable=self.term_domain, values=domains, width=12), 1), ("优先级", ttk.Entry(form, textvariable=self.term_priority, width=7), 1), ("备注", self.note_entry, 2))
        for column, (label, widget, weight) in enumerate(widgets):
            ttk.Label(form, text=label, style="Card.TLabel").grid(row=0, column=column, sticky="w", padx=(0, 8))
            widget.grid(row=1, column=column, sticky="ew", padx=(0, 8))
            form.columnconfigure(column, weight=weight)
        ttk.Button(form, text="添加", command=self._add_term, style="Accent.TButton").grid(row=1, column=len(widgets))

        actions = ttk.Frame(parent)
        actions.pack(fill="x", pady=(0, 7))
        ttk.Button(actions, text="导入 CSV", command=self._import_terms).pack(side="left")
        ttk.Button(actions, text="导出 CSV", command=self._export_terms).pack(side="left", padx=7)
        ttk.Button(actions, text="删除选中", command=self._delete_terms).pack(side="right")
        columns = ("english", "chinese", "category", "domain", "priority", "source", "note")
        self.term_tree = ttk.Treeview(parent, columns=columns, show="headings", selectmode="extended")
        for key, title, width in (("english", "英文", 200), ("chinese", "中文", 180), ("category", "类型", 80), ("domain", "领域", 100), ("priority", "优先级", 65), ("source", "来源", 190), ("note", "备注", 160)):
            self.term_tree.heading(key, text=title)
            self.term_tree.column(key, width=width, anchor="w")
        self.term_tree.pack(fill="both", expand=True)

    def _build_memory_tab(self, parent: ttk.Frame) -> None:
        intro = ttk.Frame(parent)
        intro.pack(fill="x", pady=(0, 9))
        ttk.Label(intro, text="审核过的译文会优先复用，使用次数越多，项目表达越一致。", style="Muted.TLabel").pack(side="left")
        ttk.Button(intro, text="删除选中", command=self._delete_memories).pack(side="right")
        columns = ("direction", "source", "target", "uses")
        self.memory_tree = ttk.Treeview(parent, columns=columns, show="headings", selectmode="extended")
        for key, title, width in (("direction", "方向", 80), ("source", "原文", 350), ("target", "审核译文", 350), ("uses", "使用次数", 80)):
            self.memory_tree.heading(key, text=title)
            self.memory_tree.column(key, width=width, anchor="w")
        self.memory_tree.pack(fill="both", expand=True)

    def _build_settings_tab(self, parent: ttk.Frame) -> None:
        model = ttk.Labelframe(parent, text="专业翻译模型", padding=16)
        model.pack(fill="x")
        ttk.Label(model, text="专业翻译需要一个 1.5B、Q4 量化的 GGUF 模型；未配置时自动使用快速翻译。", style="Card.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
        ttk.Entry(model, textvariable=self.model_path, state="readonly").grid(row=1, column=0, sticky="ew")
        ttk.Button(model, text="选择模型文件", command=self._select_model).grid(row=1, column=1, padx=8)
        ttk.Button(model, text="清除配置", command=self._clear_model).grid(row=1, column=2)
        ttk.Label(model, textvariable=self.model_status, style="Card.TLabel").grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))
        model.columnconfigure(0, weight=1)

        engine = ttk.Labelframe(parent, text="快速翻译引擎", padding=16)
        engine.pack(fill="x", pady=14)
        ttk.Label(engine, text="中英模型随本机数据目录保存。通常无需手动操作。", style="Card.TLabel").pack(side="left")
        ttk.Button(engine, text="手动安装 Argos 模型", command=self._install_model).pack(side="right")

        privacy = ttk.Labelframe(parent, text="隐私说明", padding=16)
        privacy.pack(fill="x")
        ttk.Label(privacy, text="所有原文、译文、术语、翻译记忆和模型推理均保留在本机，不调用云端服务。", style="Card.TLabel").pack(anchor="w")

    def _initialize_engine(self) -> None:
        threading.Thread(target=self._initialize_engine_in_background, daemon=True).start()

    def _initialize_engine_in_background(self) -> None:
        warning = self._install_bundled_models_if_needed()
        if warning:
            self.after(0, self.status.set, warning)
            return
        self.after(0, self._refresh_engine_status)

    def _translate(self) -> None:
        if self.translating:
            return
        source, target = self.direction.get().split("-")
        text = self.source_text.get("1.0", "end-1c")
        if not text.strip():
            messagebox.showinfo("没有原文", "请粘贴文字或打开一个文件")
            return
        memory = self.store.exact_memory(text, source, target)
        if memory:
            self._show_translation(TranslationResult(memory.target_text, ("已复用审核过的翻译记忆",), draft=memory.target_text, from_memory=True), text)
            return
        self.memory_hint = ""
        memory_terms = []
        reused = 0
        best_suggestion = 0.0
        for unit in segment_text(text):
            matched = self.store.exact_memory(unit, source, target)
            if matched is None:
                similar = self.store.similar_memories(unit, source, target, limit=1)
                if similar:
                    score, candidate = similar[0]
                    best_suggestion = max(best_suggestion, score)
                    if score >= 0.96 and parameter_signature(unit) == parameter_signature(candidate.source_text):
                        matched = candidate
            if matched:
                reused += 1
                if source == "en":
                    memory_terms.append(Term(None, unit, matched.target_text, category="固定短语", priority=1000, domain="翻译记忆", source="已审核记忆"))
                else:
                    memory_terms.append(Term(None, matched.target_text, unit, category="固定短语", priority=1000, domain="翻译记忆", source="已审核记忆"))
        if reused:
            self.memory_hint = f"已复用 {reused} 个审核过的句段"
        elif best_suggestion >= 0.65:
            self.memory_hint = f"发现 {best_suggestion:.0%} 相似的历史句段，可在翻译记忆页参考"
        self.translating = True
        self.translate_button.configure(state="disabled")
        self.status.set("正在本机处理，首次加载模型可能需要一些时间...")
        terms = self.store.list_terms() + memory_terms
        professional = self.mode.get() == "专业翻译"
        threading.Thread(target=self._translate_in_background, args=(text, source, target, terms, professional), daemon=True).start()

    def _translate_in_background(self, text, source, target, terms, professional) -> None:
        try:
            result = self.pipeline.translate(text, source, target, terms, professional=professional)
        except TranslationUnavailable as exc:
            self.after(0, self._translation_failed, "无法翻译", str(exc), False)
            return
        except Exception as exc:
            self.after(0, self._translation_failed, "翻译失败", f"本地翻译引擎发生错误：{exc}", True)
            return
        self.after(0, self._show_translation, result, text)

    def _show_translation(self, result: TranslationResult, source_text: str) -> None:
        for widget, value in ((self.target_text, result.text), (self.draft_text, result.draft or result.text)):
            widget.delete("1.0", "end")
            widget.insert("1.0", value)
        self.last_source = source_text
        self.last_result = result.text
        label = "专业润色完成" if result.polished else "翻译完成"
        if result.from_memory:
            label = "已命中翻译记忆"
        notices = list(result.warnings)
        if self.memory_hint and not result.from_memory:
            notices.append(self.memory_hint)
        self.status.set("；".join(notices) if notices else label + "，内容未离开本机")
        self.translating = False
        self.translate_button.configure(state="normal")

    def _translation_failed(self, title: str, detail: str, is_error: bool) -> None:
        self.translating = False
        self.translate_button.configure(state="normal")
        self.status.set(detail)
        (messagebox.showerror if is_error else messagebox.showwarning)(title, detail)

    def _remember_translation(self) -> None:
        source_text = self.source_text.get("1.0", "end-1c").strip()
        target_text = self.target_text.get("1.0", "end-1c").strip()
        if not source_text or not target_text:
            messagebox.showinfo("内容不完整", "请先完成翻译并确认译文")
            return
        source, target = self.direction.get().split("-")
        count = self.store.save_aligned_memory(source_text, target_text, source, target)
        self._refresh_memories()
        self.status.set(f"已将 {count} 个审核句段保存到翻译记忆")

    def _clear_text(self) -> None:
        for widget in (self.source_text, self.target_text, self.draft_text):
            widget.delete("1.0", "end")
        self.opened_file.set("未打开文件，可直接粘贴文字")
        self.status.set("就绪")

    def _open_file(self) -> None:
        path = filedialog.askopenfilename(title="打开待翻译文件", filetypes=(("支持的文件", "*.txt *.pdf *.docx *.xlsx"), ("所有文件", "*.*")))
        if not path:
            return
        try:
            encoding = self._choose_text_encoding(path) if Path(path).suffix.lower() == ".txt" else None
            if encoding is False:
                return
            document = extract_document(path, encoding or None)
        except DocumentError as exc:
            messagebox.showwarning("无法读取文件", str(exc))
            return
        self.source_text.delete("1.0", "end")
        self.source_text.insert("1.0", document.text)
        self.target_text.delete("1.0", "end")
        self.draft_text.delete("1.0", "end")
        self.opened_file.set(os.path.basename(path))
        self.status.set(document.warning or f"已打开 {document.kind} 文件")

    def _choose_text_encoding(self, path: str):
        candidates = text_candidates(Path(path))
        if len(candidates) == 1:
            return candidates[0].encoding
        ambiguous = candidates[0].confidence < 0.75 or candidates[0].confidence - candidates[1].confidence < 0.08
        if not ambiguous:
            return candidates[0].encoding

        dialog = tk.Toplevel(self)
        dialog.title("确认文本编码")
        dialog.geometry("720x480")
        dialog.configure(background=self.BG)
        dialog.transient(self)
        dialog.grab_set()
        selected = tk.StringVar(value=candidates[0].encoding)
        result = {"encoding": False}
        ttk.Label(dialog, text="检测到多种可能的文本编码，请选择预览正常的一项。", padding=(16, 14)).pack(fill="x")
        chooser = ttk.Combobox(
            dialog,
            textvariable=selected,
            values=tuple(candidate.encoding for candidate in candidates),
            state="readonly",
        )
        chooser.pack(fill="x", padx=16)
        preview = self._make_text_widget(dialog)
        preview.pack(fill="both", expand=True, padx=16, pady=12)

        def refresh_preview(*_args):
            candidate = next(item for item in candidates if item.encoding == selected.get())
            preview.delete("1.0", "end")
            preview.insert("1.0", candidate.text[:12000])

        def accept():
            result["encoding"] = selected.get()
            dialog.destroy()

        chooser.bind("<<ComboboxSelected>>", refresh_preview)
        buttons = ttk.Frame(dialog, padding=(16, 0, 16, 14))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="取消", command=dialog.destroy).pack(side="right")
        ttk.Button(buttons, text="使用此编码", command=accept, style="Accent.TButton").pack(side="right", padx=8)
        refresh_preview()
        self.wait_window(dialog)
        return result["encoding"]

    def _save_translation(self) -> None:
        text = self.target_text.get("1.0", "end-1c")
        if not text.strip():
            messagebox.showinfo("没有译文", "请先完成翻译")
            return
        path = filedialog.asksaveasfilename(title="保存译文", defaultextension=".txt", filetypes=(("文本文件", "*.txt"),))
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as output:
                output.write(text)
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc))
            return
        self.status.set("译文已保存")

    def _add_term(self) -> None:
        try:
            priority = int(self.term_priority.get())
            self.store.save(Term(
                None,
                self.english_entry.get(),
                self.chinese_entry.get(),
                self.note_entry.get(),
                self.term_category.get(),
                priority,
                domain=self.term_domain.get(),
            ))
        except Exception as exc:
            messagebox.showerror("无法添加", str(exc))
            return
        for entry in (self.english_entry, self.chinese_entry, self.note_entry):
            entry.delete(0, "end")
        self._refresh_terms()

    def _delete_terms(self) -> None:
        self.store.delete(int(item) for item in self.term_tree.selection())
        self._refresh_terms()

    def _refresh_terms(self) -> None:
        for item in self.term_tree.get_children():
            self.term_tree.delete(item)
        for term in self.store.list_terms():
            self.term_tree.insert("", "end", iid=str(term.id), values=(term.english, term.chinese, term.category, term.domain, term.priority, term.source, term.note))

    def _import_terms(self) -> None:
        path = filedialog.askopenfilename(title="导入术语和短语", filetypes=(("CSV 文件", "*.csv"),))
        if not path:
            return
        try:
            count = self.store.import_terms(path)
        except Exception as exc:
            messagebox.showerror("导入失败", str(exc))
            return
        self._refresh_terms()
        self.status.set(f"已导入或更新 {count} 条专业表达")

    def _export_terms(self) -> None:
        path = filedialog.asksaveasfilename(title="导出术语和短语", defaultextension=".csv", filetypes=(("CSV 文件", "*.csv"),))
        if path:
            self.status.set(f"已导出 {self.store.export_terms(path)} 条专业表达")

    def _refresh_memories(self) -> None:
        for item in self.memory_tree.get_children():
            self.memory_tree.delete(item)
        for memory in self.store.list_memories():
            direction = "英→中" if memory.source_language == "en" else "中→英"
            self.memory_tree.insert("", "end", iid=str(memory.id), values=(direction, memory.source_text, memory.target_text, memory.use_count))

    def _delete_memories(self) -> None:
        self.store.delete_memories(int(item) for item in self.memory_tree.selection())
        self._refresh_memories()

    def _select_model(self) -> None:
        path = filedialog.askopenfilename(title="选择本地润色模型", filetypes=(("GGUF 模型", "*.gguf"), ("所有文件", "*.*")))
        if not path:
            return
        self.preferences.model_path = path
        self.preferences.save(self.preferences_path)
        self.model_path.set(path)
        self.polisher = self._make_polisher()
        self.pipeline.polisher = self.polisher
        self.model_status.set(self.polisher.status())

    def _clear_model(self) -> None:
        self.preferences.model_path = ""
        self.preferences.save(self.preferences_path)
        self.model_path.set("")
        self.polisher = self._make_polisher()
        self.pipeline.polisher = self.polisher
        self.model_status.set(self.polisher.status())

    def _install_model(self) -> None:
        path = filedialog.askopenfilename(title="选择 Argos 离线模型", filetypes=(("Argos 模型", "*.argosmodel"),))
        if not path:
            return
        try:
            install_argos_package(path)
        except Exception as exc:
            messagebox.showerror("安装失败", str(exc))
            return
        self._refresh_engine_status()
        messagebox.showinfo("安装成功", "离线翻译模型已安装")

    def _install_bundled_models_if_needed(self) -> str:
        try:
            pairs = set(self.backend.available_pairs())
        except TranslationUnavailable:
            return ""
        if {("en", "zh"), ("zh", "en")} <= pairs:
            return ""
        try:
            install_bundled_packages(bundled_models_dir())
        except Exception as exc:
            return f"内置翻译模型安装失败：{exc}"
        return ""

    def _refresh_engine_status(self) -> None:
        try:
            pairs = set(self.backend.available_pairs())
        except TranslationUnavailable as exc:
            self.status.set(str(exc))
            return
        if {("en", "zh"), ("zh", "en")} <= pairs:
            self.status.set("快速翻译引擎已就绪；" + self.polisher.status())
        else:
            self.status.set("缺少中英离线翻译模型")


def main() -> None:
    app = TranslatorApp()
    app.mainloop()
