from pathlib import Path
from fastapi.testclient import TestClient
from app.config import AppConfig
from app.api.routes import create_app


def test_api_scan_execute_and_undo_flow(tmp_path: Path):
    dl = tmp_path / "Downloads"
    vida = tmp_path / "Vida"
    (vida / "02_Areas" / "01_Faculdade" / "ADS").mkdir(parents=True)
    dl.mkdir()

    pdf = vida / "02_Areas" / "AlumiGest.pdf"
    pdf.write_bytes(b"conteudo-aula")

    cfg = AppConfig(
        downloads_dir=dl,
        desktop_dir=tmp_path / "Desktop",
        documents_dir=tmp_path / "Documents",
        vida_root=vida,
        projetos_dir=tmp_path / "Projetos",
        folcolor_exe=tmp_path / "Folcolor.exe",
        db_path=tmp_path / "api.db",
    )
    app = create_app(cfg)
    client = TestClient(app)

    # 1. Dashboard HTML loads
    r_home = client.get("/")
    assert r_home.status_code == 200
    assert "Vida Organizer" in r_home.text

    # 2. Scan reports loose PDF ready to move
    r_scan = client.get("/api/scan")
    assert r_scan.status_code == 200
    data = r_scan.json()
    move_items = [i for i in data["queue"] if i["category"] == "pronto_para_mover"]
    assert len(move_items) == 1

    # 3. Execute move via API
    r_exec = client.post("/api/execute", json={"categories": ["pronto_para_mover"]})
    assert r_exec.status_code == 200
    assert r_exec.json()["executed_count"] == 1
    assert not pdf.exists()
    assert (vida / "02_Areas" / "01_Faculdade" / "ADS" / "AlumiGest.pdf").exists()

    # 4. Undo via API restores file
    r_undo = client.post("/api/undo", json={})
    assert r_undo.status_code == 200
    assert r_undo.json()["undone_count"] == 1
    assert pdf.exists()
