# Tiny, boring base image
# This is something we have to work to use only python based base image
FROM edgeinternal1uhg.optum.com/glb-docker-uhg-loc/uhg-goldenimages/python:3.12-latest-dev
# FROM centraluhg.jfrog.io/glb-docker-uhg-loc/uhg-com-optum-omms/java17-golden:onprem
USER root

# Keep Python tidy and logs unbuffered
ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install deps first for better layer caching
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy the backend code
COPY voice_backend.py .
COPY client.py .

# Copy the HTML UI (includes client.html and any assets)
COPY html/ ./html/

# Copy configuration files
COPY vitals.yml .

# Expose the correct port (updated to 8086)
EXPOSE 8086

# Run the FastAPI application with uvicorn on port 8086
ENTRYPOINT ["/usr/bin/python3", "-m", "uvicorn", "voice_backend:app", "--host", "0.0.0.0", "--port", "8086"]
