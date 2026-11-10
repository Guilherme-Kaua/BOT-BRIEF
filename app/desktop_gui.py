import os
import subprocess
import time
from pathlib import Path
from typing import Any
from app.config import AppConfig
from app.db import Database
from app.engine.executor import execute_queue_items, undo_batch
from app.engine.scanner import _build_folder_cards, scan_all


def format_bytes(b: int) -> str:
    if not b or b <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    val = float(b)
    while val >= 1024 and idx < len(units) - 1:
        val /= 1024.0
        idx += 1
    return f"{val:.2f} {units[idx]}" if idx > 1 else f"{int(val)} {units[idx]}"


class DesktopController:
    def __init__(self, config: AppConfig | None = None):
        self.config = config or AppConfig()
        self.db = Database(self.config.db_path)
        self.db.init_db()
        self.state: dict[str, Any] = {}
        self.last_scan_ts: float = 0.0

    def refresh(self, force: bool = False) -> dict[str, Any]:
        if force or not self.state or (time.time() - self.last_scan_ts) > 30.0:
            self.state = scan_all(self.config, self.db)
            self.last_scan_ts = time.time()
        self.state["last_undoable_batch"] = self.db.get_last_undoable_batch()
        self.state["rules"] = self.db.list_rules()
        self.state["history"] = self.db.list_batches(limit=15)
        return self.state

    def execute_item(self, item_id: str, include_trash: bool = False, recoverable_mode: str = "archive") -> dict[str, Any]:
        if not self.state:
            self.refresh(force=True)
        selected = [i for i in self.state.get("queue", []) if i["id"] == item_id]
        res = execute_queue_items(
            selected,
            self.db,
            self.config,
            include_destructive_trash=include_trash,
            recoverable_mode=recoverable_mode,
        )
        self._remove_executed_from_cache(res)
        return res

    def execute_categories(
        self,
        categories: list[str],
        include_trash: bool = False,
        recoverable_mode: str = "archive",
    ) -> dict[str, Any]:
        if not self.state:
            self.refresh(force=True)
        wanted = set(categories)
        selected = [i for i in self.state.get("queue", []) if i["category"] in wanted]
        res = execute_queue_items(
            selected,
            self.db,
            self.config,
            include_destructive_trash=include_trash,
            recoverable_mode=recoverable_mode,
        )
        self._remove_executed_from_cache(res)
        return res

    def _remove_executed_from_cache(self, res: dict[str, Any]) -> None:
        executed_ids = {r["id"] for r in res.get("results", []) if r.get("status") == "executed"}
        if executed_ids and self.state:
            remaining = [i for i in self.state.get("queue", []) if i["id"] not in executed_ids]
            self.state["queue"] = remaining
            self.state["summary"]["total_disorganized"] = len(remaining)
            self.state["summary"]["recoverable_bytes"] = sum(
                i["size_bytes"] for i in remaining if i["category"] == "espaco_recuperavel"
            )
            self.state["folder_cards"] = _build_folder_cards(self.config, remaining, {})
        self.state["last_undoable_batch"] = self.db.get_last_undoable_batch()
        self.state["history"] = self.db.list_batches(limit=15)

    def undo_last(self, batch_id: int | None = None) -> dict[str, Any]:
        target_id = batch_id
        if target_id is None:
            last = self.db.get_last_undoable_batch()
            if not last:
                return {"undone_count": 0, "skipped_count": 0, "details": []}
            target_id = int(last["id"])
        res = undo_batch(target_id, self.db)
        self.refresh(force=True)
        return res

    def open_in_explorer(self, path_str: str) -> None:
        p = Path(path_str)
        target = p if p.is_dir() else p.parent
        if not target.exists():
            return
        if os.name == "nt":
            if p.exists() and p.is_file():
                subprocess.Popen(["explorer", f"/select,{p}"])
            else:
                os.startfile(str(target))


def launch_desktop_app(config: AppConfig | None = None) -> None:
    import customtkinter as ctk

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")

    ctrl = DesktopController(config)
    ctrl.refresh(force=True)

    root = ctk.CTk()
    root.title("Vida Organizer — Central F:\\Vida (Desktop Nativo)")
    root.geometry("1340x820")
    root.configure(fg_color="#0b1120")

    current_filter = ctk.StringVar(value="all")
    status_var = ctk.StringVar(value="Pronto.")

    # Top Header Bar
    top_frame = ctk.CTkFrame(root, fg_color="#151f32", corner_radius=10)
    top_frame.pack(fill="x", padx=16, pady=(14, 8))

    title_box = ctk.CTkFrame(top_frame, fg_color="transparent")
    title_box.pack(side="left", padx=14, pady=10)

    lbl_title = ctk.CTkLabel(
        title_box,
        text=f"🟢 Vida Organizer · Central: {ctrl.config.vida_root}",
        font=ctk.CTkFont(size=16, weight="bold"),
        text_color="#f8fafc",
    )
    lbl_title.pack(anchor="w")

    lbl_sub = ctk.CTkLabel(
        title_box,
        textvariable=status_var,
        font=ctk.CTkFont(size=12),
        text_color="#94a3b8",
    )
    lbl_sub.pack(anchor="w")

    btn_box = ctk.CTkFrame(top_frame, fg_color="transparent")
    btn_box.pack(side="right", padx=14, pady=10)

    def do_refresh_force():
        ctrl.refresh(force=True)
        render_all()

    def do_undo():
        res = ctrl.undo_last()
        status_var.set(f"↩ Desfeito: {res['undone_count']} item(ns) restaurado(s) ao local original.")
        render_all()

    def do_apply_icons():
        res = ctrl.execute_categories(["icone_pendente"], include_trash=False)
        status_var.set(f"🎨 {res['executed_count']} ícone(s) Folcolor aplicado(s)!")
        render_all()

    def do_organize_all():
        res = ctrl.execute_categories(["pronto_para_mover", "renomear_sugerido", "icone_pendente"], include_trash=False)
        status_var.set(f"✨ Organização concluída: {res['executed_count']} item(ns) arrumado(s)!")
        render_all()

    btn_org = ctk.CTkButton(
        btn_box,
        text="✨ Organizar Tudo Agora",
        fg_color="#2563eb",
        hover_color="#1d4ed8",
        font=ctk.CTkFont(size=13, weight="bold"),
        command=do_organize_all,
    )
    btn_org.pack(side="right", padx=5)

    btn_ico = ctk.CTkButton(
        btn_box,
        text="🎨 Aplicar Ícones Folcolor",
        fg_color="#6b21a8",
        hover_color="#581c87",
        font=ctk.CTkFont(size=13, weight="bold"),
        command=do_apply_icons,
    )
    btn_ico.pack(side="right", padx=5)

    btn_undo = ctk.CTkButton(
        btn_box,
        text="↩ Desfazer última ação",
        fg_color="#334155",
        hover_color="#475569",
        font=ctk.CTkFont(size=13, weight="bold"),
        command=do_undo,
    )
    btn_undo.pack(side="right", padx=5)

    btn_ref = ctk.CTkButton(
        btn_box,
        text="🔄 Re-escanear Disco",
        fg_color="#1e293b",
        hover_color="#334155",
        width=140,
        command=do_refresh_force,
    )
    btn_ref.pack(side="right", padx=5)

    # Folder Health Cards Frame
    cards_frame = ctk.CTkFrame(root, fg_color="transparent")
    cards_frame.pack(fill="x", padx=16, pady=6)

    # Main Split Frame
    main_split = ctk.CTkFrame(root, fg_color="transparent")
    main_split.pack(fill="both", expand=True, padx=16, pady=(6, 14))
    main_split.grid_columnconfigure(0, weight=3)
    main_split.grid_columnconfigure(1, weight=2)
    main_split.grid_rowconfigure(0, weight=1)

    # Left Panel: Queue
    left_panel = ctk.CTkFrame(main_split, fg_color="#151f32", corner_radius=10)
    left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

    tabs_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
    tabs_frame.pack(fill="x", padx=12, pady=(12, 6))

    rec_batch_frame = ctk.CTkFrame(left_panel, fg_color="#451a03", corner_radius=8)

    def do_archive_all_rec():
        res = ctrl.execute_categories(["espaco_recuperavel"], include_trash=True, recoverable_mode="archive")
        status_var.set(f"📦 {res['executed_count']} item(ns) arquivado(s) em 04_Arquivo_Morto!")
        render_all()

    def do_trash_all_rec():
        res = ctrl.execute_categories(["espaco_recuperavel"], include_trash=True, recoverable_mode="trash")
        status_var.set(f"🗑️ {res['executed_count']} item(ns) enviado(s) para a Lixeira do Windows!")
        render_all()

    ctk.CTkLabel(
        rec_batch_frame,
        text="Limpeza de Espaço (Instaladores, Duplicados e .zip já extraídos):",
        font=ctk.CTkFont(size=12, weight="bold"),
        text_color="#fde68a",
    ).pack(side="left", padx=10, pady=8)

    ctk.CTkButton(
        rec_batch_frame,
        text="🗑️ Todos p/ Lixeira",
        fg_color="#991b1b",
        hover_color="#7f1d1d",
        width=130,
        height=28,
        command=do_trash_all_rec,
    ).pack(side="right", padx=6, pady=6)

    ctk.CTkButton(
        rec_batch_frame,
        text="📦 Arquivar Todos",
        fg_color="#92400e",
        hover_color="#78350f",
        width=130,
        height=28,
        command=do_archive_all_rec,
    ).pack(side="right", padx=6, pady=6)

    queue_scroll = ctk.CTkScrollableFrame(left_panel, fg_color="#0f172a", corner_radius=8)
    queue_scroll.pack(fill="both", expand=True, padx=12, pady=(4, 12))

    # Right Panel: Visual Rules & History
    right_panel = ctk.CTkFrame(main_split, fg_color="#151f32", corner_radius=10)
    right_panel.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

    ctk.CTkLabel(
        right_panel,
        text="🎨 Regras Visuais Ativas (Se → Então + Folcolor)",
        font=ctk.CTkFont(size=14, weight="bold"),
        text_color="#f8fafc",
    ).pack(anchor="w", padx=14, pady=(12, 4))

    rules_scroll = ctk.CTkScrollableFrame(right_panel, fg_color="#0f172a", corner_radius=8, height=340)
    rules_scroll.pack(fill="both", expand=True, padx=12, pady=6)

    ctk.CTkLabel(
        right_panel,
        text="🕒 Histórico Recente (Clique p/ Desfazer lote)",
        font=ctk.CTkFont(size=13, weight="bold"),
        text_color="#f8fafc",
    ).pack(anchor="w", padx=14, pady=(8, 4))

    history_scroll = ctk.CTkScrollableFrame(right_panel, fg_color="#0f172a", corner_radius=8, height=160)
    history_scroll.pack(fill="x", padx=12, pady=(2, 12))

    def set_filter(f_val: str):
        current_filter.set(f_val)
        render_queue_only()

    def make_single_action(item_id: str, inc_trash: bool, mode: str):
        def _run():
            t0 = time.perf_counter()
            res = ctrl.execute_item(item_id, include_trash=inc_trash, recoverable_mode=mode)
            dt_ms = (time.perf_counter() - t0) * 1000.0
            status_var.set(f"⚡ Executado em {dt_ms:.0f} ms ({res['executed_count']} item processado).")
            render_all()
        return _run

    def render_all():
        s = ctrl.state.get("summary", {})
        q = ctrl.state.get("queue", [])
        status_var.set(
            f"Disco C: {format_bytes(s.get('c_free_bytes', 0))} livres · "
            f"{len(q)} itens na fila · {format_bytes(s.get('recoverable_bytes', 0))} recuperáveis"
        )

        last_b = ctrl.state.get("last_undoable_batch")
        if last_b:
            btn_undo.configure(state="normal", text=f"↩ Desfazer #{last_b['id']} ({last_b['description']})")
        else:
            btn_undo.configure(state="disabled", text="↩ Desfazer última ação")

        # Health Cards
        for w in cards_frame.winfo_children():
            w.destroy()
        cards = ctrl.state.get("folder_cards", [])
        for idx, card in enumerate(cards):
            cards_frame.grid_columnconfigure(idx, weight=1)
            border_col = {"red": "#ef4444", "amber": "#f59e0b", "green": "#22c55e"}.get(
                card["status_level"], "#22c55e"
            )
            cf = ctk.CTkFrame(
                cards_frame,
                fg_color="#151f32",
                border_width=2,
                border_color=border_col,
                corner_radius=8,
            )
            cf.grid(row=0, column=idx, sticky="ew", padx=4, pady=2)
            ctk.CTkLabel(
                cf,
                text=f"{card['name']}  ·  {card['badge']}",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=border_col,
            ).pack(anchor="w", padx=10, pady=(6, 0))
            ctk.CTkLabel(
                cf,
                text=card["headline"],
                font=ctk.CTkFont(size=16, weight="bold"),
                text_color="#f8fafc",
            ).pack(anchor="w", padx=10)
            ctk.CTkLabel(
                cf,
                text=card["detail"],
                font=ctk.CTkFont(size=11),
                text_color="#94a3b8",
            ).pack(anchor="w", padx=10, pady=(0, 6))

        render_tabs()
        render_queue_only()
        render_rules_and_history()

    def render_tabs():
        for w in tabs_frame.winfo_children():
            w.destroy()
        q = ctrl.state.get("queue", [])
        counts = {
            "all": len(q),
            "pronto_para_mover": sum(1 for i in q if i["category"] == "pronto_para_mover"),
            "espaco_recuperavel": sum(1 for i in q if i["category"] == "espaco_recuperavel"),
            "renomear_sugerido": sum(1 for i in q if i["category"] == "renomear_sugerido"),
            "icone_pendente": sum(1 for i in q if i["category"] == "icone_pendente"),
        }
        tab_defs = [
            ("all", f"Todos ({counts['all']})"),
            ("pronto_para_mover", f"📁 Mover ({counts['pronto_para_mover']})"),
            ("espaco_recuperavel", f"🧹 Espaço ({counts['espaco_recuperavel']})"),
            ("renomear_sugerido", f"✏️ Renomear ({counts['renomear_sugerido']})"),
            ("icone_pendente", f"🎨 Ícones ({counts['icone_pendente']})"),
        ]
        for key, label in tab_defs:
            active = current_filter.get() == key
            ctk.CTkButton(
                tabs_frame,
                text=label,
                fg_color="#2563eb" if active else "#0f172a",
                hover_color="#1d4ed8",
                height=30,
                width=110,
                command=lambda k=key: set_filter(k),
            ).pack(side="left", padx=3)

    def render_queue_only():
        for w in queue_scroll.winfo_children():
            w.destroy()
        all_q = ctrl.state.get("queue", [])
        f_val = current_filter.get()
        items = all_q if f_val == "all" else [i for i in all_q if i["category"] == f_val]

        has_rec = any(i["category"] == "espaco_recuperavel" for i in items)
        if has_rec and f_val in {"all", "espaco_recuperavel"}:
            rec_batch_frame.pack(fill="x", padx=12, pady=(0, 6), before=queue_scroll)
        else:
            rec_batch_frame.pack_forget()

        if not items:
            ctk.CTkLabel(
                queue_scroll,
                text="✨ Tudo limpo e organizado nesta categoria!",
                font=ctk.CTkFont(size=14),
                text_color="#94a3b8",
            ).pack(pady=30)
            return

        for item in items[:80]:
            row = ctk.CTkFrame(queue_scroll, fg_color="#1e293b", corner_radius=7)
            row.pack(fill="x", padx=4, pady=4)

            fname = Path(item["source_path"]).name
            sz_txt = f" ({format_bytes(item['size_bytes'])})" if item.get("size_bytes", 0) > 0 else ""

            info = ctk.CTkFrame(row, fg_color="transparent")
            info.pack(side="left", fill="x", expand=True, padx=10, pady=6)

            ctk.CTkLabel(
                info,
                text=f"{fname}{sz_txt}",
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color="#f8fafc",
                anchor="w",
            ).pack(fill="x")
            ctk.CTkLabel(
                info,
                text=f"{item['reason']}  ·  {item['source_path']}",
                font=ctk.CTkFont(size=11),
                text_color="#94a3b8",
                anchor="w",
            ).pack(fill="x")

            act = ctk.CTkFrame(row, fg_color="transparent")
            act.pack(side="right", padx=8, pady=6)

            if item["category"] == "espaco_recuperavel":
                ctk.CTkButton(
                    act,
                    text="🗑️ Lixeira",
                    fg_color="#991b1b",
                    hover_color="#7f1d1d",
                    width=86,
                    height=28,
                    command=make_single_action(item["id"], True, "trash"),
                ).pack(side="right", padx=3)
                ctk.CTkButton(
                    act,
                    text="📦 Arquivar",
                    fg_color="#92400e",
                    hover_color="#78350f",
                    width=88,
                    height=28,
                    command=make_single_action(item["id"], True, "archive"),
                ).pack(side="right", padx=3)
            elif item["category"] == "icone_pendente":
                ctk.CTkButton(
                    act,
                    text="🎨 Aplicar Cor",
                    fg_color="#6b21a8",
                    hover_color="#581c87",
                    width=105,
                    height=28,
                    command=make_single_action(item["id"], False, "archive"),
                ).pack(side="right", padx=3)
            else:
                ctk.CTkButton(
                    act,
                    text="⚡ Organizar",
                    fg_color="#2563eb",
                    hover_color="#1d4ed8",
                    width=100,
                    height=28,
                    command=make_single_action(item["id"], False, "archive"),
                ).pack(side="right", padx=3)

            ctk.CTkButton(
                act,
                text="📂",
                fg_color="#334155",
                hover_color="#475569",
                width=34,
                height=28,
                command=lambda p=item["source_path"]: ctrl.open_in_explorer(p),
            ).pack(side="right", padx=3)

    def render_rules_and_history():
        for w in rules_scroll.winfo_children():
            w.destroy()
        for r in ctrl.state.get("rules", []):
            rc = ctk.CTkFrame(rules_scroll, fg_color="#1e293b", corner_radius=6)
            rc.pack(fill="x", padx=4, pady=4)
            kws = ", ".join(r.get("keywords", [])[:5]) or "qualquer nome"
            ctk.CTkLabel(
                rc,
                text=f"📁 {r['name']} (Folcolor #{r['folcolor_index']})",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="#60a5fa",
            ).pack(anchor="w", padx=10, pady=(6, 0))
            ctk.CTkLabel(
                rc,
                text=f"SE ({kws}) → F:\\Vida\\{r['target_subpath']}",
                font=ctk.CTkFont(size=11),
                text_color="#cbd5e1",
            ).pack(anchor="w", padx=10, pady=(0, 6))

        # Anti-Goal card
        sc = ctk.CTkFrame(rules_scroll, fg_color="#31101d", corner_radius=6)
        sc.pack(fill="x", padx=4, pady=4)
        ctk.CTkLabel(
            sc,
            text="🛡️ Trava Intocável: .git, node_modules, SteamLibrary, Riot Games, C:\\Projetos",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#fda4af",
        ).pack(anchor="w", padx=10, pady=8)

        for w in history_scroll.winfo_children():
            w.destroy()
        for b in ctrl.state.get("history", [])[:8]:
            hc = ctk.CTkFrame(history_scroll, fg_color="#1e293b", corner_radius=6)
            hc.pack(fill="x", padx=4, pady=3)
            ctk.CTkLabel(
                hc,
                text=f"#{b['id']} · {b['description']}",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#e2e8f0",
            ).pack(side="left", padx=8, pady=5)
            if not b.get("undone"):
                ctk.CTkButton(
                    hc,
                    text="↩ Desfazer",
                    fg_color="#334155",
                    width=80,
                    height=24,
                    command=lambda bid=b["id"]: (ctrl.undo_last(bid), render_all()),
                ).pack(side="right", padx=6, pady=4)
            else:
                ctk.CTkLabel(hc, text="Desfeito", font=ctk.CTkFont(size=11), text_color="#64748b").pack(
                    side="right", padx=8
                )

    render_all()
    root.mainloop()
