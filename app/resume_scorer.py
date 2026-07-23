"""Heuristic ATS-friendliness scorer for resumes/CVs."""
import re
from statistics import mean

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{7,}\d)")
URL_RE = re.compile(r"(https?://\S+|www\.\S+|linkedin\.com/\S+|github\.com/\S+)")

SECTION_HEADERS = {
    "resumen": ["resumen", "perfil profesional", "objetivo", "summary", "profile", "objective"],
    "experiencia": ["experiencia laboral", "experiencia profesional", "work experience",
                     "experience", "historial laboral", "employment history"],
    "educacion": ["educación", "educacion", "formación académica", "formacion academica",
                  "education", "academic background", "estudios"],
    "habilidades": ["habilidades", "competencias", "skills", "technical skills",
                     "tecnologías", "tecnologias", "conocimientos"],
}

ACTION_VERBS = {
    # Spanish
    "lideré", "lidere", "gestioné", "gestione", "diseñé", "disene", "implementé", "implemente",
    "desarrollé", "desarrolle", "coordiné", "coordine", "optimicé", "optimice", "logré", "logre",
    "aumenté", "aumente", "reduje", "creé", "cree", "analicé", "analice", "supervisé", "supervise",
    "planifiqué", "planifique", "ejecuté", "ejecute", "mejoré", "mejore", "capacité", "capacite",
    "negocié", "negocie", "automaticé", "automatice", "impulsé", "impulse", "dirigí", "dirigi",
    # English
    "led", "managed", "designed", "implemented", "developed", "coordinated", "optimized",
    "achieved", "increased", "reduced", "created", "analyzed", "supervised", "planned",
    "executed", "improved", "trained", "negotiated", "automated", "built", "launched",
    "delivered", "streamlined", "spearheaded", "drove",
}

STOPWORDS = {
    "de", "la", "el", "en", "y", "a", "los", "las", "un", "una", "con", "para", "por", "que",
    "se", "su", "sus", "es", "del", "al", "the", "and", "of", "to", "in", "a", "for", "on",
    "with", "is", "are", "as", "at", "by", "or", "an", "be", "this", "that", "will", "we",
    "you", "your", "our", "job", "role", "team",
}


def extract_text_from_pdf(file_stream):
    import pdfplumber
    text_parts = []
    with pdfplumber.open(file_stream) as pdf:
        for page in pdf.pages:
            text_parts.append(page.extract_text() or "")
    return "\n".join(text_parts)


def extract_text_from_docx(file_stream):
    import docx
    document = docx.Document(file_stream)
    return "\n".join(p.text for p in document.paragraphs)


def extract_text_from_txt(file_stream):
    raw = file_stream.read()
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="ignore")
    return raw


def extract_text(filename, file_stream):
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return extract_text_from_pdf(file_stream)
    if lower.endswith(".docx"):
        return extract_text_from_docx(file_stream)
    if lower.endswith(".txt"):
        return extract_text_from_txt(file_stream)
    raise ValueError("Formato no soportado. Usa PDF, DOCX o TXT.")


def _keywords_from_text(text, min_len=4):
    words = re.findall(r"[a-zA-ZÀ-ÿ]+", text.lower())
    return {w for w in words if len(w) >= min_len and w not in STOPWORDS}


def score_resume(text, job_description=None):
    text_lower = text.lower()
    words = text.split()
    word_count = len(words)
    lines = [l for l in text.split("\n") if l.strip()]

    issues = []
    suggestions = []

    # 1. Contact info (10 pts)
    has_email = bool(EMAIL_RE.search(text))
    has_phone = bool(PHONE_RE.search(text))
    has_link = bool(URL_RE.search(text)) or "linkedin" in text_lower
    contact_score = (4 if has_email else 0) + (3 if has_phone else 0) + (3 if has_link else 0)
    if not has_email:
        suggestions.append("Agrega un correo electrónico visible en la parte superior del CV.")
    if not has_phone:
        suggestions.append("Agrega un número de teléfono de contacto.")
    if not has_link:
        suggestions.append("Incluye un enlace a tu LinkedIn o portafolio.")

    # 2. Sections (20 pts, 5 c/u)
    sections_found = {key: any(kw in text_lower for kw in kws) for key, kws in SECTION_HEADERS.items()}
    sections_score = sum(5 for found in sections_found.values() if found)
    for key, found in sections_found.items():
        if not found:
            suggestions.append(f"Agrega una sección clara de '{key.capitalize()}' con encabezado estándar.")

    # 3. ATS formatting (20 pts)
    format_score = 20
    if word_count < 200:
        format_score -= 8
        issues.append("El CV parece muy corto; puede faltar contenido relevante.")
    elif word_count > 1200:
        format_score -= 5
        issues.append("El CV es muy extenso; considera resumirlo a 1-2 páginas.")

    if lines:
        avg_line_len = mean(len(l.split()) for l in lines)
        if avg_line_len < 3:
            format_score -= 5
            issues.append("El texto extraído sugiere un diseño de columnas múltiples o tablas, "
                           "lo cual puede dificultar la lectura por sistemas ATS.")

    if "\t" in text:
        format_score -= 4
        issues.append("Se detectaron tabulaciones, posible uso de tablas que los ATS no leen bien.")

    format_score = max(0, format_score)

    # 4. Content quality (20 pts)
    action_verb_count = sum(1 for w in re.findall(r"[a-zA-ZÀ-ÿ]+", text_lower) if w in ACTION_VERBS)
    quant_count = len(re.findall(r"\d+%|\$\d+|\d+\+|\b\d{2,}\b", text))
    bullet_count = sum(1 for l in lines if l.strip().startswith(("-", "•", "*", "●", "▪")))

    content_score = min(10, action_verb_count) + min(6, quant_count * 2) + min(4, bullet_count // 2)
    content_score = min(20, content_score)

    if action_verb_count < 3:
        suggestions.append("Usa más verbos de acción (lideré, desarrollé, optimicé...) al inicio de tus logros.")
    if quant_count < 2:
        suggestions.append("Cuantifica tus logros con números o porcentajes (ej. 'aumenté ventas en 20%').")
    if bullet_count < 3:
        suggestions.append("Organiza tu experiencia en viñetas cortas y concretas.")

    # 5. Keyword match vs job description (20 pts, optional)
    keyword_score = None
    matched_keywords = []
    missing_keywords = []
    if job_description and job_description.strip():
        jd_keywords = _keywords_from_text(job_description)
        for kw in jd_keywords:
            if kw in text_lower:
                matched_keywords.append(kw)
            else:
                missing_keywords.append(kw)
        match_ratio = len(matched_keywords) / len(jd_keywords) if jd_keywords else 0
        keyword_score = round(match_ratio * 20)
        if missing_keywords:
            top_missing = sorted(missing_keywords)[:10]
            suggestions.append(
                "Incluye palabras clave de la oferta que faltan en tu CV: " + ", ".join(top_missing)
            )

    total_possible = 10 + 20 + 20 + 20 + (20 if keyword_score is not None else 0)
    total_score = contact_score + sections_score + format_score + content_score + (keyword_score or 0)
    normalized = round((total_score / total_possible) * 10, 1)
    normalized = max(1.0, min(10.0, normalized))

    return {
        "score": normalized,
        "word_count": word_count,
        "breakdown": {
            "contacto": contact_score,
            "secciones": sections_score,
            "formato_ats": format_score,
            "calidad_contenido": content_score,
            "coincidencia_oferta": keyword_score,
        },
        "sections_found": sections_found,
        "matched_keywords": sorted(matched_keywords),
        "missing_keywords": sorted(missing_keywords),
        "issues": issues,
        "suggestions": suggestions,
    }
