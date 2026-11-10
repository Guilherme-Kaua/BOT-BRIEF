import json
import shutil
from pathlib import Path
from send2trash import send2trash
from app.config import AppConfig
from app.db import Database
from app.engine.duplicates import _sha256_file
from app.engine.folcolor import (
    apply_folcolor_icon,
    get_category_icon_resource,
    needs_folcolor_icon,
    restore_folcolor_icon,
)
from app.engine.protector import is_file_locked, is_protected_path


def resolve_collision_path(target_path: Path, source_path: Path) -> Path:
    dst = Path(target_path)
    src = Path(source_path)
    if not dst.exists() or dst.resolve() == src.resolve():
        return dst

    version = 2
    while True:
        candidate = dst.parent / f"{dst.stem}_v{version}{dst.suffix}"
        if not candidate.exists():
            return candidate
        version += 1


def execute_queue_items(
    items: list[dict],
    db: Database,
    config: AppConfig,
    include_destructive_trash: bool = False,
    recoverable_mode: str = "archive",
) -> dict:
    executed_records: list[dict] = []
    results: list[dict] = []
    skipped_count = 0

    for item in items:
        cat = item.get("category", "")
        src_str = item.get("source_path", "")
        dst_str = item.get("target_path", "")
        src = Path(src_str)

        if not src.exists() or is_protected_path(src, config.projetos_dir) or is_file_locked(src):
            skipped_count += 1
            results.append({"id": item.get("id"), "status": "skipped", "reason": "Arquivo ausente, protegido ou em uso"})
            continue

        try:
            if cat in {"pronto_para_mover", "renomear_sugerido"}:
                dst = Path(dst_str)
                dst.parent.mkdir(parents=True, exist_ok=True)
                if (
                    dst.exists()
                    and dst.is_file()
                    and src.is_file()
                    and dst.resolve() != src.resolve()
                    and dst.stat().st_size == src.stat().st_size
                    and _sha256_file(dst) == _sha256_file(src)
                ):
                    skipped_count += 1
                    results.append(
                        {
                            "id": item.get("id"),
                            "status": "skipped",
                            "reason": "Arquivo idêntico (mesmo SHA-256) já existe no destino",
                        }
                    )
                    continue
                final_dst = resolve_collision_path(dst, src)
                shutil.move(str(src), str(final_dst))

                # Ensure parent folder inside F:\Vida has its Folcolor icon applied
                if needs_folcolor_icon(final_dst.parent, config.vida_root, config.folcolor_exe):
                    res_icon = get_category_icon_resource(final_dst.parent, config.vida_root, config.folcolor_exe)
                    if res_icon:
                        apply_folcolor_icon(final_dst.parent, res_icon)

                action_type = "rename" if cat == "renomear_sugerido" else "move"
                executed_records.append(
                    {
                        "action_type": action_type,
                        "source_path": str(src),
                        "target_path": str(final_dst),
                        "meta_json": json.dumps({"rule_name": item.get("rule_name", "")}, ensure_ascii=False),
                    }
                )
                results.append({"id": item.get("id"), "status": "executed", "target_path": str(final_dst)})

            elif cat == "icone_pendente":
                res_icon = get_category_icon_resource(src, config.vida_root, config.folcolor_exe)
                if not res_icon:
                    idx = int(item.get("folcolor_index", 13))
                    res_icon = (
                        f"{config.folcolor_exe},{idx}"
                        if config.folcolor_exe.exists()
                        else "C:\\Windows\\System32\\shell32.dll,3"
                    )
                applied = apply_folcolor_icon(src, res_icon)
                executed_records.append(
                    {
                        "action_type": "icon",
                        "source_path": str(src),
                        "target_path": str(src),
                        "meta_json": json.dumps(
                            {"previous_content": applied["previous_content"]}, ensure_ascii=False
                        ),
                    }
                )
                results.append({"id": item.get("id"), "status": "executed", "target_path": str(src)})

            elif cat == "espaco_recuperavel":
                if not include_destructive_trash:
                    skipped_count += 1
                    results.append(
                        {"id": item.get("id"), "status": "skipped", "reason": "Requer confirmação de limpeza"}
                    )
                    continue
                if recoverable_mode == "trash":
                    send2trash(str(src))
                    executed_records.append(
                        {
                            "action_type": "trash",
                            "source_path": str(src),
                            "target_path": "RecycleBin",
                            "meta_json": json.dumps({"note": "Enviado para a Lixeira do Windows"}, ensure_ascii=False),
                        }
                    )
                    results.append({"id": item.get("id"), "status": "executed", "target_path": "RecycleBin"})
                else:
                    archive_dst = Path(
                        dst_str
                        or str(config.vida_root / "04_Arquivo_Morto" / "Limpeza_Downloads" / src.name)
                    )
                    archive_dst.parent.mkdir(parents=True, exist_ok=True)
                    final_dst = resolve_collision_path(archive_dst, src)
                    shutil.move(str(src), str(final_dst))
                    executed_records.append(
                        {
                            "action_type": "archive",
                            "source_path": str(src),
                            "target_path": str(final_dst),
                            "meta_json": "{}",
                        }
                    )
                    results.append({"id": item.get("id"), "status": "executed", "target_path": str(final_dst)})
            else:
                skipped_count += 1
        except OSError as exc:
            skipped_count += 1
            results.append({"id": item.get("id"), "status": "error", "reason": str(exc)})

    batch_id: int | None = None
    if executed_records:
        batch_id = db.record_batch(
            f"Organização ({len(executed_records)} item(ns))",
            executed_records,
        )

    return {
        "batch_id": batch_id,
        "executed_count": len(executed_records),
        "skipped_count": skipped_count,
        "results": results,
    }


def undo_batch(batch_id: int, db: Database) -> dict:
    batch = db.get_batch(batch_id)
    if not batch or batch.get("undone"):
        return {"undone_count": 0, "skipped_count": 0, "details": []}

    undone_count = 0
    skipped_count = 0
    details: list[dict] = []

    for item in reversed(batch.get("items", [])):
        action_type = item["action_type"]
        src = Path(item["source_path"])
        dst = Path(item["target_path"])
        meta = json.loads(item.get("meta_json") or "{}")

        try:
            if action_type in {"move", "rename", "archive"}:
                if not dst.exists():
                    skipped_count += 1
                    details.append(
                        {"source_path": str(src), "status": "skipped", "reason": "Arquivo não encontrado no destino"}
                    )
                    continue
                src.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dst), str(src))
                undone_count += 1
                details.append({"source_path": str(src), "status": "restored"})
            elif action_type == "icon":
                restore_folcolor_icon(src, meta.get("previous_content"))
                undone_count += 1
                details.append({"source_path": str(src), "status": "icon_restored"})
            else:
                skipped_count += 1
                details.append(
                    {
                        "source_path": str(src),
                        "status": "skipped",
                        "reason": "Item enviado à Lixeira do Windows (restaurar pela Lixeira)",
                    }
                )
        except OSError as exc:
            skipped_count += 1
            details.append({"source_path": str(src), "status": "error", "reason": str(exc)})

    db.mark_batch_undone(batch_id)
    return {
        "undone_count": undone_count,
        "skipped_count": skipped_count,
        "details": details,
    }

