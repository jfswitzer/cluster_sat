FROM python:3.11-slim-bullseye
WORKDIR /app
COPY grader.py .
COPY submission.py .
# Ensure we see updates by printing a timestamp
RUN echo "Built at: $(date)" > /app/build_info.txt
ENTRYPOINT ["python", "grader.py"]
