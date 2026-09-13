FROM python:3.12-slim

# ifcopenshell ships its own OCCT build, so only the loader bits are needed here
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir manifold3d

COPY B2GM_*.py ./
COPY web/ ./web/
COPY XSD/ ./XSD/
COPY input_data/ ./input_data/

# the demo converts the bundled sample once at build time, so the first visitor
# sees a model instead of an empty canvas
RUN python B2GM_main.py --output-dir output \
 && python B2GM_main.py --citygml-version 3.0 --output-dir output/citygml_3.0

RUN useradd --create-home --uid 10001 b2gm && chown -R b2gm /app
USER b2gm

ENV B2GM_HOST=0.0.0.0 \
    PORT=8080 \
    PYTHONUNBUFFERED=1
EXPOSE 8080

CMD ["python", "B2GM_web.py", "--no-browser"]
