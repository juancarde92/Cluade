import io
import os

from flask import Flask, render_template, request

from resume_scorer import extract_text, score_resume

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}


@app.route("/", methods=["GET"])
def index():
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
    return render_template("index.html", result=result, filename=file.filename, error=None)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
