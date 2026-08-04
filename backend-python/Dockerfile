FROM python:3.12-slim

WORKDIR /app
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# System deps:
#   gcc + libpq-dev   → psycopg2 compilation
#   curl              → healthcheck
#   libgomp1          → OpenMP (required by onnxruntime used by fastembed)
#   fonts-dejavu-core → Unicode text in generated PDFs. reportlab's built-in
#                       faces are Latin-1 only, so maths and science glyphs
#                       (ℝ, ⁻¹, vectors) would print as hollow boxes.
#   fonts-noto-core   → Noto Naskh Arabic, for Urdu. DejaVu carries almost none
#                       of the Urdu-specific letters (ٹ ڈ ڑ ں ھ ے).
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    libgomp1 \
    fonts-dejavu-core \
    fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Upload directories (overridden by volume in production)
RUN mkdir -p uploads/documents uploads/submissions

EXPOSE 8000

ENTRYPOINT ["bash", "start.sh"]
