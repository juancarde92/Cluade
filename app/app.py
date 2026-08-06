import io
import os

from flask import Flask, Response, render_template, request

import analytics
from resume_scorer import extract_text, score_resume

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
WHATSAPP_NUMBER = os.environ.get("WHATSAPP_NUMBER", "573185572550")
ADMIN_STATS_PASSWORD = os.environ.get("ADMIN_STATS_PASSWORD")


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

    return render_template(
        "index.html", result=result, filename=file.filename, error=None,
        whatsapp_number=WHATSAPP_NUMBER, whatsapp_message=whatsapp_message,
    )


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
    conversion = round((analyses / stats["visits"] * 100), 1) if stats.get("visits") else 0
    return render_template("admin_stats.html", stats=stats, conversion=conversion)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
