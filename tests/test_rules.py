from pathlib import Path
from app.db import Database
from app.engine.rules import (
    suggest_clean_name,
    is_unstandardized_folder_name,
    evaluate_file,
)


def test_accent_and_case_insensitive_rule_matching(tmp_path: Path):
    db = Database(tmp_path / "rules.db")
    db.init_db()
    rules = db.list_rules()

    f1 = tmp_path / "Curriculo_Guilherme_Kaua.DOCX"
    f1.write_text("doc")
    m1 = evaluate_file(f1, "02_Areas", rules)
    assert m1 is not None
    assert "04_Docs_Pessoais" in m1["target_subpath"]

    f2 = tmp_path / "Testes Não Funcionais — Usabilidade.PPTX"
    f2.write_text("ppt")
    m2 = evaluate_file(f2, "Downloads", rules)
    assert m2 is not None
    assert "01_Faculdade" in m2["target_subpath"]

    f3 = tmp_path / "TJPB.apkg"
    f3.write_text("anki")
    m3 = evaluate_file(f3, "02_Areas", rules)
    assert m3 is not None
    assert "01.2_Biblioteca_Concursos" in m3["target_subpath"]


def test_suggest_clean_name_handles_hash_whatsapp_and_gemini(tmp_path: Path):
    p1 = tmp_path / "3270425600f6bde5b7f8e4a2917a6339.jpg"
    p1.write_text("img")
    clean1 = suggest_clean_name(p1)
    assert clean1 is not None
    assert clean1.startswith("Img_") and clean1.endswith("_327042.jpg")

    p2 = tmp_path / "WhatsApp Image 2026-10-27 at 12.17.06.jpeg"
    p2.write_text("img")
    assert suggest_clean_name(p2) == "WhatsApp_2026-10-27_12h17.jpeg"

    p3 = tmp_path / "AlumiGest_Resumo.pdf"
    p3.write_text("pdf")
    assert suggest_clean_name(p3) is None


def test_unstandardized_folder_detection():
    assert is_unstandardized_folder_name("Nova pasta") is True
    assert is_unstandardized_folder_name("Projet 2") is True
    assert is_unstandardized_folder_name("01_Faculdade") is False
