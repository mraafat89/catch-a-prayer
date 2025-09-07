FROM python:3.11-slim

WORKDIR /app

# Install system dependencies including Chrome for Selenium
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    gnupg \
    unzip \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

# Install Chrome - support both amd64 and arm64
ARG TARGETARCH
RUN if [ "$TARGETARCH" = "amd64" ]; then \
        wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/googlearchive-keyring.gpg \
        && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/googlearchive-keyring.gpg] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list \
        && apt-get update \
        && apt-get install -y google-chrome-stable \
        && rm -rf /var/lib/apt/lists/*; \
    else \
        apt-get update \
        && apt-get install -y chromium chromium-driver \
        && rm -rf /var/lib/apt/lists/*; \
    fi

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]