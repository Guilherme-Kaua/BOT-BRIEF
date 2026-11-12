import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import AppConfig, FOLCOLOR_CATEGORY_MAP
from app.db import Database
from app.engine.protector import is_active_download, is_protected_path
from app.engine.rules import normalize_text

SMART_TAGS_CATALOG: list[tuple[str, str]] = [
    ("Estudar", "#3b82f6"),
    ("Trabalho", "#10b981"),
    ("Pessoal", "#ec4899"),
    ("Importante", "#ef4444"),
    ("Temporário", "#f59e0b"),
    ("Revisar", "#8b5cf6"),
]

STOP_WORDS_PT: set[str] = {
    "o",
    "a",
    "os",
    "as",
    "um",
    "uma",
    "uns",
    "umas",
    "de",
    "do",
    "da",
    "dos",
    "das",
    "em",
    "no",
    "na",
    "nos",
    "nas",
    "por",
    "para",
    "com",
    "sem",
    "sobre",
    "que",
    "qual",
    "aquele",
    "aquela",
    "aqueles",
    "aquelas",
    "este",
    "esta",
    "esse",
    "essa",
    "isso",
    "arquivo",
    "arquivos",
    "pasta",
    "baixei",
    "salvei",
    "criei",
    "fiz",
    "estava",
    "onde",
    "meu",
    "minha",
    "meus",
    "minhas",
    "passado",
    "passada",
    "ultimo",
    "ultima",
    "este",
    "mes",
    "semana",
    "ano",
    "hoje",
    "ontem",
}

SEMANTIC_TYPE_MAP: dict[str, set[str]] = {
    "pdf": {".pdf", ".epub"},
    "apostila": {".pdf", ".docx", ".epub"},
    "livro": {".pdf", ".epub"},
    "artigo": {".pdf", ".docx", ".md"},
    "edital": {".pdf"},
    "prova": {".pdf", ".docx"},
    "planilha": {".xlsx", ".xls", ".csv"},
    "tabela": {".xlsx", ".xls", ".csv"},
    "orcamento": {".xlsx", ".xls", ".csv", ".pdf"},
    "documento": {".pdf", ".docx", ".doc", ".md", ".txt"},
    "texto": {".md", ".txt", ".docx", ".pdf"},
    "resumo": {".md", ".txt", ".docx", ".pdf"},
    "slide": {".pptx", ".ppt", ".pdf"},
    "apresentacao": {".pptx", ".ppt", ".pdf"},
    "imagem": {".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".svg"},
    "foto": {".png", ".jpg", ".jpeg", ".webp"},
    "print": {".png", ".jpg", ".jpeg", ".webp"},
    "video": {".mp4", ".mkv", ".mov", ".avi"},
    "gravacao": {".mp4", ".mkv", ".mov"},
    "zip": {".zip", ".rar", ".7z"},
    "compactado": {".zip", ".rar", ".7z"},
    "instalador": {".exe", ".msi", ".msix"},
    "programa": {".exe", ".msi"},
}

CONCEPT_SYNONYMS_PT: list[set[str]] = [
    {
        "estruturas",
        "dados",
        "algoritmos",
        "arvore",
        "arvores",
        "binaria",
        "binarias",
        "lista",
        "listas",
        "pilha",
        "pilhas",
        "grafo",
        "grafos",
        "sistemas",
        "orientados",
        "wazlawick",
        "ads",
        "programacao",
        "codigo",
    },
    {
        "faculdade",
        "ads",
        "aula",
        "estudar",
        "estudo",
        "sprint",
        "alumigest",
        "wazlawick",
        "usabilidade",
        "disponibilidade",
        "apostila",
        "trabalho",
        "academico",
    },
    {
        "concurso",
        "concursos",
        "prf",
        "tjpb",
        "aci",
        "edital",
        "prova",
        "objetiva",
        "anki",
        "ciclo",
        "studyn",
        "estudar",
    },
    {
        "financeiro",
        "orcamento",
        "gastos",
        "nota",
        "fiscal",
        "boleto",
        "comprovante",
        "imposto",
        "planilha",
        "dinheiro",
    },
    {
        "pessoal",
        "curriculo",
        "rg",
        "cpf",
        "historico",
        "certidao",
        "contrato",
        "documento",
    },
    {
        "jogo",
        "jogos",
        "game",
        "fps",
        "fpspack",
        "valorant",
        "islc",
        "r2modman",
        "ps2",
        "bios",
        "emulador",
        "mod",
    },
]

TEXT_READABLE_EXTENSIONS: set[str] = {
    ".txt",
    ".md",
    ".json",
    ".csv",
    ".py",
    ".js",
    ".html",
    ".css",
    ".xml",
    ".ini",
    ".log",
    ".pdf",
}


def suggest_smart_tags(path: Path) -> list[str]:
    norm_full = normalize_text(str(path))
    ext = path.suffix.lower()
    suggestions: list[str] = []

    if any(k in norm_full for k in ("faculdade", "ads", "concurso", "aula", "apostila", "anki", "wazlawick", "estudo")):
        suggestions.append("Estudar")
    if any(k in norm_full for k in ("projeto", "sprint", "alumigest", "relatorio", "ata", "trabalho", "pr review")):
        suggestions.append("Trabalho")
    if any(k in norm_full for k in ("pessoal", "curriculo", "rg", "cpf", "whatsapp", "foto", "saude")):
        suggestions.append("Pessoal")
    if any(k in norm_full for k in ("contrato", "certidao", "nota fiscal", "comprovante", "edital")):
        suggestions.append("Importante")
    if ext in {".exe", ".msi", ".tmp", ".part", ".crdownload", ".zip", ".rar"} or "downloads" in norm_full:
        suggestions.append("Temporário")
    if "99 inbox" in norm_full or "outros arquivos" in norm_full:
        suggestions.append("Revisar")

    return suggestions


def _extract_lightweight_snippet(path: Path, max_bytes: int = 24576) -> str:
    if path.suffix.lower() not in TEXT_READABLE_EXTENSIONS:
        return ""
    try:
        with open(path, "rb") as f:
            raw = f.read(max_bytes)
        if path.suffix.lower() == ".pdf":
            # Extract UTF-8/Latin-1 printable words from PDF stream headers/text
            decoded_pdf = raw.decode("utf-8", errors="ignore") + " " + raw.decode("latin-1", errors="ignore")
            words = re.findall(r"[A-Za-zÀ-ÿ0-9_\-]{3,}", decoded_pdf)
            return normalize_text(" ".join(words[:500]))
        return normalize_text(raw.decode("utf-8", errors="ignore"))
    except OSError:
        return ""


def parse_natural_query(query: str) -> dict[str, Any]:
    norm_q = normalize_text(query)

    # 1. Detect time window (min_age_days, max_age_days)
    time_window: tuple[float, float] | None = None
    time_label: str | None = None
    if "hoje" in norm_q:
        time_window = (0.0, 1.5)
        time_label = "Hoje"
    elif "ontem" in norm_q:
        time_window = (0.4, 2.8)
        time_label = "Ontem"
    elif "semana passada" in norm_q or "ultima semana" in norm_q:
        time_window = (4.0, 16.0)
        time_label = "Semana passada"
    elif "esta semana" in norm_q or "nessa semana" in norm_q:
        time_window = (0.0, 8.0)
        time_label = "Esta semana"
    elif "mes passado" in norm_q or "ultimo mes" in norm_q:
        time_window = (14.0, 65.0)
        time_label = "Mês passado (~15 a 60 dias)"
    elif "este mes" in norm_q or "nesse mes" in norm_q:
        time_window = (0.0, 32.0)
        time_label = "Este mês"

    # 2. Detect target file extensions from natural words
    wanted_exts: set[str] = set()
    tokens = norm_q.split()
    for tok in tokens:
        if tok in SEMANTIC_TYPE_MAP:
            wanted_exts |= SEMANTIC_TYPE_MAP[tok]

    # 3. Extract meaningful tokens & expand synonyms
    core_tokens = [
        t
        for t in tokens
        if t not in STOP_WORDS_PT and t not in SEMANTIC_TYPE_MAP and len(t) >= 2
    ]
    expanded_terms: set[str] = set(core_tokens)
    for tok in core_tokens:
        for syn_group in CONCEPT_SYNONYMS_PT:
            if tok in syn_group or any(tok in s or s in tok for s in syn_group if len(tok) >= 4):
                expanded_terms |= syn_group

    return {
        "raw_query": query,
        "normalized": norm_q,
        "core_tokens": core_tokens,
        "expanded_terms": expanded_terms,
        "wanted_exts": wanted_exts,
        "time_window": time_window,
        "time_label": time_label,
    }


def _collect_searchable_files(config: AppConfig) -> list[Path]:
    roots = [
        config.downloads_dir,
        config.desktop_dir,
        config.documents_dir,
    ]
    for cat in FOLCOLOR_CATEGORY_MAP:
        roots.append(config.vida_root / cat)

    results: list[Path] = []
    seen: set[str] = set()

    def _walk(d: Path, depth: int, max_depth: int) -> None:
        if depth > max_depth or not d.exists():
            return
        try:
            entries = sorted(d.iterdir(), key=lambda p: p.name.lower())
        except (PermissionError, OSError):
            return
        for e in entries:
            if e.name.lower() == "desktop.ini" or e.name.startswith("."):
                continue
            if is_protected_path(e, config.projetos_dir):
                continue
            if e.is_file() and not is_active_download(e):
                k = str(e).lower()
                if k not in seen:
                    seen.add(k)
                    results.append(e)
            elif e.is_dir() and depth < max_depth:
                _walk(e, depth + 1, max_depth)

    for r in roots:
        _walk(r, 0, 3 if str(r).lower().startswith(str(config.vida_root).lower()) else 1)
    return results


def semantic_search_files(
    query: str,
    config: AppConfig,
    db: Database,
    tag_filter: str | None = None,
    now_ts: float | None = None,
    limit: int = 80,
) -> list[dict[str, Any]]:
    cur_ts = now_ts if now_ts is not None else time.time()
    parsed = parse_natural_query(query)
    tags_map = db.get_all_file_tags_map()
    candidates = _collect_searchable_files(config)

    # Also include any explicitly tagged file even if outside standard depth
    existing_keys = {str(p).lower() for p in candidates}
    for tagged_path_low in tags_map:
        if tagged_path_low not in existing_keys:
            tp = Path(tagged_path_low)
            if tp.exists() and tp.is_file():
                candidates.append(tp)

    scored_results: list[dict[str, Any]] = []

    for f in candidates:
        f_key = str(f).lower()
        explicit_tags = tags_map.get(f_key, [])
        auto_tags = suggest_smart_tags(f)
        all_tags = list(dict.fromkeys([*explicit_tags, *auto_tags]))

        if tag_filter and tag_filter != "all":
            if not any(t.lower() == tag_filter.lower() for t in all_tags):
                continue

        try:
            st = f.stat()
            sz = st.st_size
            mtime = st.st_mtime
        except OSError:
            continue

        age_days = max(0.0, (cur_ts - mtime) / 86400.0)
        ext = f.suffix.lower()
        norm_name = normalize_text(f.name)
        norm_path = normalize_text(str(f.parent))
        norm_tags = normalize_text(" ".join(all_tags))

        # If query is empty and user is just browsing by Smart Tag
        if not query.strip():
            scored_results.append(
                {
                    "name": f.name,
                    "path": str(f),
                    "folder": str(f.parent),
                    "size_bytes": sz,
                    "modified_date": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"),
                    "age_days": round(age_days, 1),
                    "tags": all_tags,
                    "explicit_tags": explicit_tags,
                    "score": 100 if explicit_tags else 80,
                    "match_reason": f"Etiqueta: {', '.join(all_tags)}" if all_tags else "Arquivo indexado",
                }
            )
            continue

        score = 0
        reasons: list[str] = []

        # 1. File type semantic match
        if parsed["wanted_exts"]:
            if ext in parsed["wanted_exts"]:
                score += 30
                reasons.append(f"Tipo compatível ({ext})")
            else:
                score -= 25

        # 2. Time window match
        if parsed["time_window"]:
            min_d, max_d = parsed["time_window"]
            if min_d <= age_days <= max_d:
                score += 30
                reasons.append(f"Período: {parsed['time_label']} ({int(age_days)}d atrás)")
            else:
                score -= 15

        # 3. Direct token matches in filename, path, or tags
        direct_hits = [tok for tok in parsed["core_tokens"] if tok in norm_name or tok in norm_tags]
        if direct_hits:
            score += 45 * len(direct_hits)
            reasons.append(f"Termo direto: {', '.join(direct_hits[:3])}")

        # 4. Concept / synonym matches in filename, folder path, tags, or file content
        snippet = _extract_lightweight_snippet(f) if parsed["expanded_terms"] else ""
        combined_context = f"{norm_name} {norm_path} {norm_tags} {snippet}"
        syn_hits = [term for term in parsed["expanded_terms"] if term in combined_context]
        if syn_hits:
            score += min(60, 18 * len(syn_hits))
            reasons.append(f"Semântica/Conteúdo: {', '.join(sorted(syn_hits)[:4])}")

        # 5. Prioritize explicitly tagged files (especially when filtering by that tag)
        has_explicit_filter_match = bool(
            tag_filter
            and tag_filter != "all"
            and any(t.lower() == tag_filter.lower() for t in explicit_tags)
        )
        if has_explicit_filter_match:
            score += 25
            reasons.append(f"Etiqueta manual: {tag_filter}")
        elif explicit_tags:
            score += 10

        if score > 15:
            scored_results.append(
                {
                    "name": f.name,
                    "path": str(f),
                    "folder": str(f.parent),
                    "size_bytes": sz,
                    "modified_date": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"),
                    "age_days": round(age_days, 1),
                    "tags": all_tags,
                    "explicit_tags": explicit_tags,
                    "score": min(100, score),
                    "_rank_key": (
                        1 if has_explicit_filter_match else 0,
                        1 if explicit_tags else 0,
                        score,
                        -age_days,
                    ),
                    "match_reason": " · ".join(reasons) if reasons else "Correspondência contextual",
                }
            )

    scored_results.sort(
        key=lambda r: r.get(
            "_rank_key",
            (0, 1 if r.get("explicit_tags") else 0, r["score"], -r["age_days"]),
        ),
        reverse=True,
    )
    for r in scored_results:
        r.pop("_rank_key", None)
    return scored_results[:limit]
