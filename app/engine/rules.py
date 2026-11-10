import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path

HEX_HASH_RE = re.compile(r"^[0-9a-f]{8,}(?:[._-][0-9a-f]{4,})*$", re.IGNORECASE)
NUMERIC_ONLY_RE = re.compile(r"^\d{5,}$")
WHATSAPP_EN_RE = re.compile(
    r"^whatsapp\s+(?:image|video)\s+(\d{4}-\d{2}-\d{2})\s+at\s+(\d{2})[.:](\d{2})",
    re.IGNORECASE,
)
WHATSAPP_PT_RE = re.compile(
    r"^(?:imagem|video|vídeo)\s+do\s+whatsapp\s+de\s+(\d{4}-\d{2}-\d{2}).*?(\d{2})[.:](\d{2})",
    re.IGNORECASE,
)
GEMINI_RE = re.compile(r"^gemini_generated_image_([a-z0-9]{6,})", re.IGNORECASE)

UNSTANDARDIZED_FOLDER_PATTERNS = [
    re.compile(r"^nova\s+pasta(?:\s*\(\d+\)|\s+\d+)?$", re.IGNORECASE),
    re.compile(r"^new\s+folder(?:\s*\(\d+\)|\s+\d+)?$", re.IGNORECASE),
    re.compile(r"^projet(?:\s+\d+)?$", re.IGNORECASE),
    re.compile(r"^teste(?:\s+.*)?$", re.IGNORECASE),
    re.compile(r"^prova\s+amanha$", re.IGNORECASE),
    re.compile(r"^estudo\s+prova$", re.IGNORECASE),
]


MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".mp4"}


def normalize_text(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    without_accents = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return re.sub(r"[-_\s]+", " ", without_accents).strip().lower()


def suggest_clean_name(path: Path) -> str | None:
    p = Path(path)
    stem = p.stem
    ext = p.suffix.lower()

    m_en = WHATSAPP_EN_RE.match(stem)
    if m_en:
        date_str, hh, mm = m_en.group(1), m_en.group(2), m_en.group(3)
        return f"WhatsApp_{date_str}_{hh}h{mm}{ext}"

    m_pt = WHATSAPP_PT_RE.match(stem)
    if m_pt:
        date_str, hh, mm = m_pt.group(1), m_pt.group(2), m_pt.group(3)
        return f"WhatsApp_{date_str}_{hh}h{mm}{ext}"

    try:
        mtime = p.stat().st_mtime if p.exists() else time.time()
    except OSError:
        mtime = time.time()
    date_prefix = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")

    m_gem = GEMINI_RE.match(stem)
    if m_gem:
        short_id = m_gem.group(1)[:6].lower()
        return f"Gemini_{date_prefix}_{short_id}{ext}"

    if ext in MEDIA_EXTENSIONS and (
        (HEX_HASH_RE.match(stem) and len(stem) >= 16) or NUMERIC_ONLY_RE.match(stem)
    ):
        short_id = re.sub(r"[^0-9a-f]", "", stem.lower())[:6]
        return f"Img_{date_prefix}_{short_id}{ext}"

    return None


def is_unstandardized_folder_name(name: str) -> bool:
    norm = normalize_text(name.strip())
    return any(pat.match(norm) for pat in UNSTANDARDIZED_FOLDER_PATTERNS)


def evaluate_file(
    path: Path,
    source_scope: str,
    rules: list[dict],
    now_ts: float | None = None,
) -> dict | None:
    p = Path(path)
    current_ts = now_ts if now_ts is not None else time.time()
    is_dir = p.is_dir()
    ext = "dir" if is_dir else p.suffix.lower().lstrip(".")
    norm_name = normalize_text(p.name)
    norm_scope = normalize_text(source_scope)

    try:
        mtime = p.stat().st_mtime if p.exists() else current_ts
    except OSError:
        mtime = current_ts
    age_days = max(0.0, (current_ts - mtime) / 86400.0)

    sorted_rules = sorted(rules, key=lambda r: (int(r.get("priority", 50)), int(r.get("id", 0))))

    for rule in sorted_rules:
        if not int(rule.get("enabled", 1)):
            continue

        scopes = [normalize_text(s) for s in rule.get("source_scopes", ["*"])]
        if "*" not in scopes and norm_scope not in scopes:
            continue

        min_age = float(rule.get("min_age_days", 0))
        if age_days < min_age:
            continue

        allowed_exts = [normalize_text(e).lstrip(".") for e in rule.get("extensions", [])]
        if allowed_exts and ext not in allowed_exts:
            continue

        keywords = [normalize_text(k) for k in rule.get("keywords", []) if k.strip()]
        if keywords:
            if not any(kw in norm_name for kw in keywords):
                continue

        return {
            "rule_id": rule.get("id"),
            "rule_name": rule["name"],
            "category_folder": rule["category_folder"],
            "target_subpath": rule["target_subpath"],
            "folcolor_index": int(rule.get("folcolor_index", 13)),
        }

    return None

