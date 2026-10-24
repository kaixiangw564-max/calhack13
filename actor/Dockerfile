FROM apify/actor-python:3.11

USER myuser

COPY --chown=myuser:myuser requirements.txt ./
RUN pip install -r requirements.txt && pip freeze

COPY --chown=myuser:myuser . ./
RUN python -m compileall -q src/

CMD ["python", "-m", "src"]
