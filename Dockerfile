FROM node:22-bookworm-slim AS node

FROM python:3.12-slim-bookworm
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && npm install --global @openai/codex@0.162.1 \
    && npm cache clean --force
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY pyproject.toml README.md ./
COPY ppt_workbench ./ppt_workbench
RUN pip install --no-cache-dir . \
    && groupadd --gid 1001 weppt \
    && useradd --uid 1000 --gid 1001 --create-home weppt \
    && mkdir -p /data /home/weppt/.codex \
    && chown -R weppt:weppt /data /home/weppt
ENV HOME=/home/weppt PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER weppt
ENTRYPOINT ["pptctl", "--root", "/data", "studio"]
CMD ["--project", "main", "--port", "8766", "--agent", "codex"]
