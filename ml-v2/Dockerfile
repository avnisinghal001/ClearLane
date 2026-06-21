FROM python:3.11-slim

# Create a non-root user matching Hugging Face specifications
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:${PATH}"

WORKDIR /app

# Copy and install dependencies under user privileges
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# Copy the rest of the application files securely
COPY --chown=user . .

EXPOSE 7860

# CMD aligned with main.py entrypoint structure
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]