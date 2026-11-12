import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.config import AppConfig
from app.db import Database
from app.engine.duplicates import build_duplicate_groups
from app.engine.executor import execute_queue_items
from app.engine.rules import evaluate_file, suggest_clean_name

MENU_ENTRIES: list[tuple[str, str, str]] = [
    ("01_Organize", "Organizar com Vida Organizer", "--ctx-organize"),
    ("02_SendVida", "Enviar para F:\\Vida", "--ctx-send-vida"),
    ("03_Pin", "Adicionar aos fixados (Ignorar)", "--ctx-pin"),
    ("04_Duplicates", "Analisar duplicados", "--ctx-duplicates"),
    ("05_OpenTarget", "Abrir pasta de destino", "--ctx-open-target"),
]


def get_default_launcher_paths() -> tuple[str, str]:
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe" and (exe.parent / "pythonw.exe").exists():
        exe = exe.parent / "pythonw.exe"
    main_py = Path(__file__).resolve().parent.parent / "main.py"
    return str(exe), str(main_py)


def build_context_menu_spec(
    python_exe: str | None = None,
    main_py: str | None = None,
) -> dict[str, Any]:
    py_exe, main_script = get_default_launcher_paths()
    py_exe = python_exe or py_exe
    main_script = main_py or main_script

    entries: list[dict[str, str]] = []
    for sub_id, label, flag in MENU_ENTRIES:
        cmd = f'"{py_exe}" "{main_script}" {flag} "%1"'
        entries.append(
            {
                "id": sub_id,
                "label": label,
                "flag": flag,
                "command": cmd,
            }
        )

    reg_lines = [
        "Windows Registry Editor Version 5.00",
        "",
    ]
    for scope in ("*", "Directory"):
        base_key = f"HKEY_CURRENT_USER\\Software\\Classes\\{scope}\\shell\\VidaOrganizer"
        shell_key = f"HKEY_CURRENT_USER\\Software\\Classes\\{scope}\\shell\\VidaOrganizer\\shell"
        reg_lines.append(f"[{base_key}]")
        reg_lines.append('"MUIVerb"="Vida Organizer"')
        reg_lines.append('"SubCommands"=""')
        reg_lines.append(f'"Icon"="{py_exe},0"')
        reg_lines.append("")
        for e in entries:
            ek = f"{shell_key}\\{e['id']}"
            ek_cmd = f"{ek}\\command"
            esc_cmd = e["command"].replace("\\", "\\\\").replace('"', '\\"')
            reg_lines.append(f"[{ek}]")
            reg_lines.append(f'"MUIVerb"="{e["label"]}"')
            reg_lines.append("")
            reg_lines.append(f"[{ek_cmd}]")
            reg_lines.append(f'@="{esc_cmd}"')
            reg_lines.append("")

    return {
        "entries": entries,
        "reg_content": "\r\n".join(reg_lines),
        "hkcu_roots": [
            r"Software\Classes\*\shell\VidaOrganizer",
            r"Software\Classes\Directory\shell\VidaOrganizer",
        ],
    }


def is_context_menu_installed() -> bool:
    if os.name != "nt":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\*\shell\VidaOrganizer"):
            return True
    except OSError:
        return False


def install_context_menu(
    python_exe: str | None = None,
    main_py: str | None = None,
) -> dict[str, Any]:
    spec = build_context_menu_spec(python_exe=python_exe, main_py=main_py)
    if os.name != "nt":
        return {"installed": False, "reason": "Somente Windows", "spec": spec}

    import winreg

    ico_path = Path(__file__).resolve().parent.parent / "static" / "vida_organizer.ico"
    icon_val = str(ico_path) if ico_path.exists() else f"{(python_exe or sys.executable)},0"

    for scope in ("*", "Directory"):
        base_path = rf"Software\Classes\{scope}\shell\VidaOrganizer"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base_path) as k:
            winreg.SetValueEx(k, "MUIVerb", 0, winreg.REG_SZ, "Vida Organizer")
            winreg.SetValueEx(k, "SubCommands", 0, winreg.REG_SZ, "")
            winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, icon_val)

        for e in spec["entries"]:
            sub_path = rf"{base_path}\shell\{e['id']}"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, sub_path) as sk:
                winreg.SetValueEx(sk, "MUIVerb", 0, winreg.REG_SZ, e["label"])
            cmd_path = rf"{sub_path}\command"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, cmd_path) as ck:
                winreg.SetValueEx(ck, "", 0, winreg.REG_SZ, e["command"])

    return {"installed": True, "entries": len(spec["entries"])}


def _delete_reg_tree(root_hive: Any, subkey: str) -> None:
    import winreg

    try:
        with winreg.OpenKey(root_hive, subkey, 0, winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                    _delete_reg_tree(root_hive, rf"{subkey}\{child}")
                except OSError:
                    break
        winreg.DeleteKey(root_hive, subkey)
    except OSError:
        pass


def uninstall_context_menu() -> dict[str, Any]:
    if os.name != "nt":
        return {"uninstalled": False}
    import winreg

    for scope in ("*", "Directory"):
        _delete_reg_tree(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{scope}\shell\VidaOrganizer")
    return {"uninstalled": True}


def _predict_target_for_path(target: Path, config: AppConfig, db: Database) -> tuple[Path, str, str]:
    rules = db.list_rules()
    matched = evaluate_file(target, target.parent.name, rules)
    if matched:
        clean_name = suggest_clean_name(target.name) or target.name
        dst = config.vida_root / matched["target_subpath"] / clean_name
        return dst, matched["rule_name"], f"Regra '{matched['rule_name']}'"
    clean_name = suggest_clean_name(target.name) or target.name
    dst = config.vida_root / "99_Inbox" / clean_name
    return dst, "Inbox Padrão", "Enviado para 99_Inbox"


def execute_context_menu_action(
    action: str,
    target_path: str,
    config: AppConfig,
    db: Database,
    open_explorer: bool = True,
) -> dict[str, Any]:
    p = Path(target_path)
    if not p.exists():
        return {"status": "error", "action": action, "message": f"Caminho não encontrado: {p}"}

    if action == "pin":
        db.add_ignored_path(str(p), "Fixado pelo menu de contexto do Explorer")
        return {"status": "ok", "action": action, "path": str(p), "message": f"{p.name} adicionado aos Fixados."}

    if action in {"organize", "send_vida"}:
        if action == "organize":
            dst, rule_name, reason = _predict_target_for_path(p, config, db)
        else:
            clean_name = suggest_clean_name(p.name) or p.name
            dst = config.vida_root / "99_Inbox" / clean_name
            rule_name = "Menu de Contexto → F:\\Vida"
            reason = "Enviado manualmente para F:\\Vida pelo Explorer"

        try:
            sz = p.stat().st_size if p.is_file() else 0
        except OSError:
            sz = 0
        item = {
            "id": f"ctx_{p.name}",
            "category": "pronto_para_mover",
            "source_path": str(p),
            "target_path": str(dst),
            "size_bytes": sz,
            "rule_name": rule_name,
            "reason": reason,
        }
        res = execute_queue_items([item], db, config)
        return {"status": "ok", "action": action, "result": res, "target_path": str(dst)}

    if action == "duplicates":
        groups = build_duplicate_groups(config)
        p_low = str(p).lower()
        matching = [
            g
            for g in groups
            if g["keeper"]["path"].lower() == p_low
            or any(ex["path"].lower() == p_low for ex in g.get("extras", []))
            or p.stem.lower() in g["title"].lower()
        ]
        return {
            "status": "ok",
            "action": action,
            "path": str(p),
            "matching_groups": matching,
            "all_groups_count": len(groups),
        }

    if action == "open_target":
        dst, rule_name, _reason = _predict_target_for_path(p, config, db)
        target_dir = dst.parent
        target_dir.mkdir(parents=True, exist_ok=True)
        if open_explorer and os.name == "nt":
            subprocess.Popen(["explorer", str(target_dir)])
        return {
            "status": "ok",
            "action": action,
            "target_dir": str(target_dir),
            "predicted_file": str(dst),
            "rule_name": rule_name,
        }

    return {"status": "error", "action": action, "message": f"Ação desconhecida: {action}"}

