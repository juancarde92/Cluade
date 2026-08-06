import io
import os
import tempfile
import uuid

from flask import Flask, Response, render_template, request, send_file

import analytics
from harvard_cv import DEFAULT_LANGUAGE, LANGUAGES, TEMPLATE_CHOICES, build_docx, rewrite_resume_harvard
from resume_scorer import extract_text, score_resume

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
WHATSAPP_NUMBER = os.environ.get("WHATSAPP_NUMBER", "573185572550")
ADMIN_STATS_PASSWORD = os.environ.get("ADMIN_STATS_PASSWORD")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
MAX_LANGUAGES = 2

# In-memory store for resumes awaiting Harvard-style generation. A
# single-process deployment (e.g. Render free tier) keeps this alive
# between the /analyze request and the follow-up /harvard/generate call
# for the same visitor.
PENDING_RESUMES = {}

# Generated files waiting to be downloaded: file_token -> {"path", "filename"}
READY_FILES = {}


def _harvard_enabled():
    return bool(GEMINI_API_KEY)


@app.route("/", methods=["GET"])
def index():
    analytics.increment("visits")
    return render_template("index.html", result=None)


@app.route("/analyze", methods=["POST"])
def analyze():
    file = request.files.get("resume")
    job_description = request.form.get("job_description", "")

    if not file or file.filename == "":
        return render_template("index.html", result=None, error="Por favor sube un archivo de hoja de vida.")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return render_template("index.html", result=None,
                                error="Formato no soportado. Usa PDF, DOCX o TXT.")

    try:
        text = extract_text(file.filename, io.BytesIO(file.read()))
    except Exception as exc:
        return render_template("index.html", result=None,
                                error=f"No se pudo leer el archivo: {exc}")

    if not text.strip():
        return render_template("index.html", result=None,
                                error="No se pudo extraer texto del archivo. Verifica que no sea una imagen escaneada.")

    result = score_resume(text, job_description)
    analytics.increment("analyses")
    whatsapp_message = (
        f"Hola, acabo de calificar mi hoja de vida con el Calificador ATS y obtuve "
        f"{result['score']}/10. Quiero asesoría para mejorarla."
    )

    token = uuid.uuid4().hex
    PENDING_RESUMES[token] = {"text": text, "filename": file.filename}

    return render_template(
        "index.html", result=result, filename=file.filename, error=None,
        whatsapp_number=WHATSAPP_NUMBER, whatsapp_message=whatsapp_message,
        harvard_token=token, harvard_enabled=_harvard_enabled(),
        harvard_templates=TEMPLATE_CHOICES, harvard_languages=LANGUAGES,
    )


def _register_file(path, filename):
    file_token = uuid.uuid4().hex
    READY_FILES[file_token] = {"path": path, "filename": filename}
    return file_token


@app.route("/harvard/generate/<token>", methods=["POST"])
def harvard_generate(token):
    if not _harvard_enabled():
        return render_template("index.html", result=None,
                                error="La generación de CV estilo Harvard no está disponible todavía.")
    entry = PENDING_RESUMES.get(token)
    if not entry:
        return render_template("index.html", result=None,
                                error="Tu sesión expiró. Vuelve a subir tu CV para generar la versión Harvard.")

    template_choice = request.form.get("template_choice", "")
    languages = [lang for lang in request.form.getlist("languages") if lang in LANGUAGES]

    if template_choice not in TEMPLATE_CHOICES:
        return render_template("index.html", result=None, error="Selecciona una plantilla de CV válida.")
    if not languages:
        return render_template("index.html", result=None, error="Selecciona al menos un idioma para tu CV.")
    if len(languages) > MAX_LANGUAGES:
        return render_template("index.html", result=None,
                                error=f"Selecciona máximo {MAX_LANGUAGES} idiomas para tu CV.")

    files = []
    try:
        for lang in languages:
            data = rewrite_resume_harvard(entry["text"], language_code=lang)
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
                build_docx(template_choice, data, tmp.name, language_code=lang)
                tmp_path = tmp.name
            lang_label = LANGUAGES[lang]["label"]
            file_token = _register_file(tmp_path, f"CV_Harvard_{lang}.docx")
            files.append({"label": f"CV Harvard ({lang_label})", "token": file_token})
    except Exception as exc:
        return render_template("index.html", result=None,
                                error=f"No pudimos generar tu CV: {exc}. Inténtalo de nuevo o escríbenos por WhatsApp.")

    PENDING_RESUMES.pop(token, None)
    analytics.increment("harvard_generations")
    return render_template(
        "index.html", result=None, error=None,
        harvard_success=True, download_files=files,
    )


@app.route("/harvard/download/<file_token>")
def harvard_download(file_token):
    entry = READY_FILES.get(file_token)
    if not entry or not os.path.exists(entry["path"]):
        return render_template("index.html", result=None,
                                error="Ese enlace de descarga ya no está disponible. Vuelve a generar tu CV.")
    return send_file(entry["path"], as_attachment=True, download_name=entry["filename"])


def _check_admin_auth():
    auth = request.authorization
    return bool(ADMIN_STATS_PASSWORD) and auth and auth.password == ADMIN_STATS_PASSWORD


@app.route("/admin/stats")
def admin_stats():
    if not ADMIN_STATS_PASSWORD:
        return render_template("index.html", result=None, error="Panel de métricas no configurado."), 404
    if not _check_admin_auth():
        return Response(
            "Autenticación requerida.", 401,
            {"WWW-Authenticate": 'Basic realm="Metricas"'},
        )

    stats = analytics.get_stats()
    analyses = stats.get("analyses", 0)
    generations = stats.get("harvard_generations", 0)
    conversion = round((generations / analyses * 100), 1) if analyses else 0
    return render_template("admin_stats.html", stats=stats, conversion=conversion)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
