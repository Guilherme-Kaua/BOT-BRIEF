from dataclasses import dataclass, field
from pathlib import Path

FOLCOLOR_CATEGORY_MAP: dict[str, int] = {
    "00_Jogos": 4,
    "01_Projetos": 6,
    "02_Areas": 9,
    "03_Recursos": 8,
    "04_Arquivo_Morto": 15,
    "99_Inbox": 2,
}

VIDA_ROOT_ICON_INDEX: int = 13


@dataclass
class AppConfig:
    downloads_dir: Path = field(default_factory=lambda: Path.home() / "Downloads")
    desktop_dir: Path = field(default_factory=lambda: Path.home() / "Desktop")
    documents_dir: Path = field(default_factory=lambda: Path.home() / "Documents")
    vida_root: Path = field(default_factory=lambda: Path("F:/Vida"))
    projetos_dir: Path = field(default_factory=lambda: Path("C:/Projetos"))
    folcolor_exe: Path = field(default_factory=lambda: Path("C:/Program Files (x86)/Folcolor/Folcolor.exe"))
    db_path: Path = field(
        default_factory=lambda: Path(__file__).resolve().parent.parent / "data" / "vida_organizer.db"
    )
    downloads_cooldown_minutes: int = 120
    vida_root_cooldown_minutes: int = 15
    port: int = 18420

