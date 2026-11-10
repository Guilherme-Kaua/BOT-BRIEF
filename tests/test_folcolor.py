import ctypes
from pathlib import Path
from app.engine.folcolor import (
    get_category_icon_resource,
    needs_folcolor_icon,
    apply_folcolor_icon,
    scan_missing_icons,
)


def test_apply_folcolor_overwrites_existing_hidden_system_desktop_ini(tmp_path: Path):
    vida = tmp_path / "Vida"
    sub = vida / "02_Areas" / "01_Faculdade"
    sub.mkdir(parents=True)
    fake_folcolor = tmp_path / "Folcolor.exe"
    fake_folcolor.write_text("exe")

    resource = get_category_icon_resource(sub, vida, fake_folcolor)
    assert resource == f"{fake_folcolor},9"
    assert needs_folcolor_icon(sub, vida, fake_folcolor) is True

    # First application sets HIDDEN | SYSTEM on desktop.ini
    res1 = apply_folcolor_icon(sub, resource)
    assert res1["previous_content"] is None
    ini_path = sub / "desktop.ini"
    assert ini_path.exists()
    assert needs_folcolor_icon(sub, vida, fake_folcolor) is False

    # Second application must succeed without PermissionError even when desktop.ini is Hidden+System
    new_resource = f"{fake_folcolor},6"
    res2 = apply_folcolor_icon(sub, new_resource)
    assert "IconResource=" in (res2["previous_content"] or "")
    assert new_resource in ini_path.read_text(encoding="utf-8")


def test_scan_missing_icons_covers_first_and_second_level_subfolders(tmp_path: Path):
    vida = tmp_path / "Vida"
    sub1 = vida / "03_Recursos" / "01.2_Biblioteca_Concursos"
    sub2 = sub1 / "Matematica"
    sub2.mkdir(parents=True)
    fake_folcolor = tmp_path / "Folcolor.exe"
    fake_folcolor.write_text("exe")

    missing = scan_missing_icons(vida, fake_folcolor, max_depth=2)
    paths = {Path(item["path"]) for item in missing}
    assert sub1 in paths
    assert sub2 in paths


def test_custom_folcolor_icon_on_subfolder_is_preserved_and_vida_tree_built(tmp_path: Path):
    from app.engine.folcolor import build_vida_tree

    vida = tmp_path / "Vida"
    sub = vida / "02_Areas" / "02_Financeiro"
    sub.mkdir(parents=True)
    fake_folcolor = tmp_path / "Folcolor.exe"
    fake_folcolor.write_text("exe")

    # Apply custom green icon (#6) to a subfolder inside 02_Areas (default #9)
    apply_folcolor_icon(sub, f"{fake_folcolor},6")
    assert needs_folcolor_icon(sub, vida, fake_folcolor) is False

    fake_queue = [
        {
            "category": "pronto_para_mover",
            "source_path": str(tmp_path / "Downloads" / "boleto.pdf"),
            "target_path": str(sub / "boleto.pdf"),
        }
    ]
    tree = build_vida_tree(vida, fake_folcolor, fake_queue)
    fin_nodes = [n for n in tree if Path(n["path"]) == sub]
    assert len(fin_nodes) == 1
    assert fin_nodes[0]["current_folcolor_index"] == 6
    assert fin_nodes[0]["incoming_count"] == 1


