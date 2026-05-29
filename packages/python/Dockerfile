FROM python:3.9-alpine

WORKDIR /app

# Copy the workspace and install the split packages. Install core first so the
# adapter packages resolve their bankhub-core dependency from the local build.
COPY . .
RUN pip install --no-cache-dir ./bankhub-core \
  && pip install --no-cache-dir ./bankhub-files ./bankhub-connectors

USER nobody

# bankhub-core installs the `bankhub` console script (same CLI as before).
ENTRYPOINT ["bankhub"]
