import io
import os
import tempfile
import uuid

import stripe
from flask import Flask, redirect, render_template, request, send_file

from resume_scorer import extract_text, score_resume

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
WHATSAPP_NUMBER = os.environ.get("WHATSAPP_NUMBER", "573185572550")

STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
HARVARD_CV_PRICE_COP = int(os.environ.get("HARVARD_CV_PRICE_COP", "25000"))
BASE_URL = os.environ.get("BASE_URL", "http://localhost:5000")
if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# In-memory store for resumes awaiting payment. A single-process deployment
# (e.g. Render free tier) keeps this alive between the /analyze request and
# the Stripe redirect back to /harvard/success for the same visitor.
PENDING_RESUMES = {}


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
        harvard_enabled=bool(STRIPE_SECRET_KEY and os.environ.get("ANTHROPIC_API_KEY")),
    )


@app.route("/checkout/<token>", methods=["POST"])
def checkout(token):
    if not STRIPE_SECRET_KEY or not os.environ.get("ANTHROPIC_API_KEY"):
        return render_template("index.html", result=None,
                                error="La generación de CV estilo Harvard no está disponible todavía.")
    if token not in PENDING_RESUMES:
        return render_template("index.html", result=None,
                                error="Tu sesión expiró. Vuelve a subir tu CV para generar la versión Harvard.")

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[{
                "price_data": {
                    "currency": "cop",
                    "product_data": {"name": "CV estilo Harvard (formato DOCX)"},
                    "unit_amount": HARVARD_CV_PRICE_COP * 100,
                },
                "quantity": 1,
            }],
            metadata={"token": token},
            success_url=f"{BASE_URL}/harvard/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{BASE_URL}/",
        )
    except Exception:
        return render_template("index.html", result=None,
                                error="No se pudo iniciar el pago. Intenta de nuevo en unos minutos.")
    return redirect(session.url, code=303)


@app.route("/harvard/success")
def harvard_success():
    session_id = request.args.get("session_id")
    if not session_id:
        return render_template("index.html", result=None, error="Sesión de pago inválida.")

    try:
        session = stripe.checkout.Session.retrieve(session_id)
    except Exception:
        return render_template("index.html", result=None, error="No se pudo verificar el pago.")

    if session.payment_status != "paid":
        return render_template("index.html", result=None, error="El pago no se completó.")

    token = (session.metadata or {}).get("token")
    entry = PENDING_RESUMES.pop(token, None)
    if not entry:
        return render_template("index.html", result=None,
                                error="No se encontró tu CV original. Vuelve a subirlo y genera de nuevo.")

    from harvard_cv import build_harvard_docx, rewrite_resume_harvard

    try:
        data = rewrite_resume_harvard(entry["text"])
    except Exception as exc:
        return render_template("index.html", result=None,
                                error=f"Se procesó tu pago pero no pudimos generar el CV: {exc}. "
                                      f"Escríbenos por WhatsApp para resolverlo.")

    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        build_harvard_docx(data, tmp.name)
        tmp_path = tmp.name

    return send_file(tmp_path, as_attachment=True, download_name="CV_Harvard.docx")


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
