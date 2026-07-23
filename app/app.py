import hashlib
import io
import os
import tempfile
import uuid
from urllib.parse import urlencode

import requests
from flask import Flask, redirect, render_template, request, send_file

from harvard_cv import TEMPLATE_CHOICES, build_docx, rewrite_resume_harvard
from resume_scorer import extract_text, score_resume

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
WHATSAPP_NUMBER = os.environ.get("WHATSAPP_NUMBER", "573185572550")

WOMPI_PUBLIC_KEY = os.environ.get("WOMPI_PUBLIC_KEY")
WOMPI_INTEGRITY_SECRET = os.environ.get("WOMPI_INTEGRITY_SECRET")
WOMPI_API_BASE = (
    "https://sandbox.wompi.co/v1" if (WOMPI_PUBLIC_KEY or "").startswith("pub_test_")
    else "https://production.wompi.co/v1"
)
HARVARD_CV_PRICE_COP = int(os.environ.get("HARVARD_CV_PRICE_COP", "25000"))
BASE_URL = os.environ.get("BASE_URL", "http://localhost:5000")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# In-memory store for resumes awaiting payment. A single-process deployment
# (e.g. Render free tier) keeps this alive between the /analyze request and
# the Wompi redirect back to /harvard/success for the same visitor.
PENDING_RESUMES = {}

# Generated docx files waiting to be downloaded from the confirmation page.
READY_FILES = {}


def _harvard_enabled():
    return bool(WOMPI_PUBLIC_KEY and WOMPI_INTEGRITY_SECRET and GEMINI_API_KEY)


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
    whatsapp_message = (
        f"Hola, acabo de calificar mi hoja de vida con el Calificador ATS y obtuve "
        f"{result['score']}/10. Quiero asesoría para mejorarla."
    )

    token = uuid.uuid4().hex
    PENDING_RESUMES[token] = {"text": text, "filename": file.filename}

    return render_template(
        "index.html", result=result, filename=file.filename, error=None,
        whatsapp_number=WHATSAPP_NUMBER, whatsapp_message=whatsapp_message,
        harvard_token=token, harvard_price=HARVARD_CV_PRICE_COP,
        harvard_enabled=_harvard_enabled(), harvard_templates=TEMPLATE_CHOICES,
    )


@app.route("/checkout/<token>", methods=["POST"])
def checkout(token):
    if not _harvard_enabled():
        return render_template("index.html", result=None,
                                error="La generación de CV estilo Harvard no está disponible todavía.")
    if token not in PENDING_RESUMES:
        return render_template("index.html", result=None,
                                error="Tu sesión expiró. Vuelve a subir tu CV para generar la versión Harvard.")

    template_choice = request.form.get("template_choice", "")
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip()
    phone = request.form.get("phone", "").strip()

    if template_choice not in TEMPLATE_CHOICES:
        return render_template("index.html", result=None, error="Selecciona una plantilla de CV válida.")
    if not full_name or not email or not phone:
        return render_template("index.html", result=None,
                                error="Completa tu nombre completo, correo y celular para continuar.")

    PENDING_RESUMES[token].update({
        "template_choice": template_choice,
        "full_name": full_name,
        "email": email,
        "phone": phone,
    })

    amount_in_cents = HARVARD_CV_PRICE_COP * 100
    currency = "COP"
    signature = hashlib.sha256(
        f"{token}{amount_in_cents}{currency}{WOMPI_INTEGRITY_SECRET}".encode()
    ).hexdigest()

    params = {
        "public-key": WOMPI_PUBLIC_KEY,
        "currency": currency,
        "amount-in-cents": amount_in_cents,
        "reference": token,
        "signature:integrity": signature,
        "redirect-url": f"{BASE_URL}/harvard/success",
        "customer-data:email": email,
        "customer-data:full-name": full_name,
        "customer-data:phone-number": phone,
    }
    return redirect(f"https://checkout.wompi.co/p/?{urlencode(params)}", code=303)


@app.route("/harvard/success")
def harvard_success():
    transaction_id = request.args.get("id")
    if not transaction_id:
        return render_template("index.html", result=None, error="Pago inválido o cancelado.")

    try:
        resp = requests.get(
            f"{WOMPI_API_BASE}/transactions/{transaction_id}",
            headers={"Authorization": f"Bearer {WOMPI_PUBLIC_KEY}"},
            timeout=10,
        )
        resp.raise_for_status()
        transaction = resp.json()["data"]
    except Exception:
        return render_template("index.html", result=None, error="No se pudo verificar el pago.")

    if transaction.get("status") != "APPROVED":
        return render_template("index.html", result=None,
                                error=f"El pago no se completó (estado: {transaction.get('status', 'desconocido')}).")

    token = transaction.get("reference")
    # Keep the entry until the docx is actually built and ready to download, so a
    # customer who already paid can just reload this URL to retry after a
    # transient failure instead of having to pay again.
    entry = PENDING_RESUMES.get(token)
    if not entry or "template_choice" not in entry:
        return render_template("index.html", result=None,
                                error="No se encontró tu CV original. Escríbenos por WhatsApp con tu "
                                      "comprobante de pago para resolverlo.")

    try:
        data = rewrite_resume_harvard(entry["text"])
    except Exception as exc:
        return render_template("index.html", result=None,
                                error=f"Se procesó tu pago pero no pudimos generar el CV: {exc}. "
                                      f"Recarga esta página para reintentar, o escríbenos por WhatsApp.")

    try:
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            build_docx(entry["template_choice"], data, tmp.name)
            tmp_path = tmp.name
    except Exception:
        return render_template("index.html", result=None,
                                error="Se procesó tu pago pero no pudimos armar el archivo docx. "
                                      "Recarga esta página para reintentar, o escríbenos por WhatsApp.")

    file_token = uuid.uuid4().hex
    READY_FILES[file_token] = tmp_path

    PENDING_RESUMES.pop(token, None)
    return render_template(
        "index.html", result=None, error=None,
        harvard_success=True, download_token=file_token,
        customer_name=entry.get("full_name", ""),
    )


@app.route("/harvard/download/<file_token>")
def harvard_download(file_token):
    tmp_path = READY_FILES.get(file_token)
    if not tmp_path or not os.path.exists(tmp_path):
        return render_template("index.html", result=None,
                                error="Ese enlace de descarga ya no está disponible. Escríbenos por WhatsApp.")
    return send_file(tmp_path, as_attachment=True, download_name="CV_Harvard.docx")


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
