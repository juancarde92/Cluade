# Calificador de Hojas de Vida ATS

Aplicación web en Flask que califica una hoja de vida (CV) de 1 a 10 según qué tan bien está optimizada para sistemas ATS (*Applicant Tracking System*) y reclutadores.

## Cómo funciona

Sube tu CV en PDF, DOCX o TXT (opcionalmente pega la descripción de una oferta de trabajo) y la app evalúa:

- **Información de contacto** (10 pts): correo, teléfono, LinkedIn/portafolio.
- **Secciones estándar** (20 pts): Resumen, Experiencia, Educación, Habilidades.
- **Formato compatible con ATS** (20 pts): longitud adecuada, sin columnas/tablas que rompan el parseo.
- **Calidad del contenido** (20 pts): verbos de acción, logros cuantificados, viñetas.
- **Coincidencia con la oferta** (20 pts, opcional): palabras clave de la descripción del puesto presentes en el CV.

El puntaje total se normaliza a una escala de 1 a 10, junto con una lista de problemas detectados y sugerencias concretas de mejora.

## Instalación

```bash
cd app
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Ejecutar

```bash
python app.py
```

Abre http://localhost:5000 en tu navegador.

## Estructura

```
app.py              # rutas Flask
resume_scorer.py     # lógica de extracción de texto y scoring
templates/index.html # UI
static/style.css     # estilos
```
