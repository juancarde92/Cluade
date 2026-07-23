"""Rewrite a resume into Harvard-style content and render it as a .docx."""
import json
import os
import re

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

SYSTEM_PROMPT = (
    "Eres un experto en redacción de hojas de vida en el formato estándar de Harvard "
    "(Harvard Office of Career Services). Reescribes el contenido de un CV existente: "
    "mejoras la redacción, usas verbos de acción fuertes al inicio de cada logro, "
    "cuantificas resultados cuando sea razonable inferirlo del texto original (sin "
    "inventar cifras que no estén sugeridas), y mantienes un tono profesional y conciso. "
    "No inventes experiencia, empresas, cargos o títulos que no existan en el CV original; "
    "solo mejora la redacción y organización de lo que ya está ahí."
)

RESPONSE_SCHEMA_HINT = """
Responde ÚNICAMENTE con un JSON válido (sin markdown, sin explicación adicional) con esta forma exacta:
{
  "name": "Nombre completo",
  "contact_line": "correo · teléfono · ciudad · linkedin",
  "summary": "2-3 líneas de resumen profesional",
  "education": [
    {"school": "Universidad", "location": "Ciudad, País", "degree": "Título obtenido", "dates": "Año inicio - Año fin"}
  ],
  "experience": [
    {"organization": "Empresa", "location": "Ciudad, País", "title": "Cargo", "dates": "Mes Año - Mes Año",
     "bullets": ["Logro reescrito 1", "Logro reescrito 2"]}
  ],
  "skills": "Lista de habilidades y herramientas separadas por comas"
}
"""


def rewrite_resume_harvard(raw_text):
    import google.generativeai as genai

    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    model = genai.GenerativeModel(model_name, system_instruction=SYSTEM_PROMPT)
    response = model.generate_content(
        f"Aquí está el texto extraído de un CV (puede tener errores de formato "
        f"por la extracción):\n\n---\n{raw_text}\n---\n\n{RESPONSE_SCHEMA_HINT}"
    )
    text = response.text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    return json.loads(text)


def _add_bottom_border(paragraph):
    p = paragraph._p
    p_pr = p.get_or_add_pPr()
    p_bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "000000")
    p_bdr.append(bottom)
    p_pr.append(p_bdr)


def _add_section_heading(doc, text):
    p = doc.add_paragraph()
    run = p.add_run(text.upper())
    run.bold = True
    run.font.size = Pt(12)
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(4)
    _add_bottom_border(p)
    return p


def _add_entry_line(doc, left_text, location, dates):
    left_text = str(left_text or "")
    location = str(location or "")
    dates = str(dates or "")
    p = doc.add_paragraph()
    p.paragraph_format.tab_stops.add_tab_stop(Inches(6.4), WD_TAB_ALIGNMENT.RIGHT)
    left = left_text if not location else f"{left_text}, {location}"
    run = p.add_run(left)
    run.bold = True
    p.add_run("\t" + dates)
    return p


def _as_list(value):
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def build_harvard_docx(data, output_path):
    if not isinstance(data, dict):
        data = {}
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(11)

    for section in doc.sections:
        section.top_margin = Inches(0.7)
        section.bottom_margin = Inches(0.7)
        section.left_margin = Inches(0.8)
        section.right_margin = Inches(0.8)

    name_p = doc.add_paragraph()
    name_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = name_p.add_run(str(data.get("name") or "").upper())
    run.bold = True
    run.font.size = Pt(16)

    contact_p = doc.add_paragraph()
    contact_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    contact_p.add_run(str(data.get("contact_line") or ""))

    summary = data.get("summary")
    if summary:
        _add_section_heading(doc, "Resumen Profesional")
        doc.add_paragraph(str(summary))

    education = _as_list(data.get("education"))
    if education:
        _add_section_heading(doc, "Educación")
        for edu in education:
            _add_entry_line(doc, edu.get("school", ""), edu.get("location", ""), edu.get("dates", ""))
            if edu.get("degree"):
                p = doc.add_paragraph()
                p.add_run(str(edu["degree"])).italic = True

    experience = _as_list(data.get("experience"))
    if experience:
        _add_section_heading(doc, "Experiencia Profesional")
        for job in experience:
            _add_entry_line(doc, job.get("organization", ""), job.get("location", ""), job.get("dates", ""))
            if job.get("title"):
                p = doc.add_paragraph()
                p.add_run(str(job["title"])).italic = True
            bullets = job.get("bullets", [])
            if not isinstance(bullets, list):
                bullets = [bullets]
            for bullet in bullets:
                bp = doc.add_paragraph(style="List Bullet")
                bp.add_run(str(bullet))

    skills = data.get("skills")
    if isinstance(skills, list):
        skills = ", ".join(str(s) for s in skills)
    if skills:
        _add_section_heading(doc, "Habilidades y Herramientas")
        doc.add_paragraph(str(skills))

    doc.save(output_path)
