FROM python:3.11-slim-bullseye
WORKDIR /app
COPY grader.py .
COPY submission.py .
RUN echo "Built at: $(date)" > /app/build_info.txt
ENTRYPOINT ["python", "grader.py"]
