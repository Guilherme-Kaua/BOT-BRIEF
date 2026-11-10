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

