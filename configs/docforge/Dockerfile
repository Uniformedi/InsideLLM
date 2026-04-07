FROM node:20-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-core \
    libreoffice-writer \
    libreoffice-calc \
    libreoffice-impress \
    fonts-liberation \
    fonts-dejavu-core \
    curl \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json ./
RUN npm install --production && npm cache clean --force

COPY src/ ./src/

RUN useradd -r -s /bin/false docforge \
  && mkdir -p /app/data/temp \
  && chown -R docforge:docforge /app

USER docforge

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:3000/health || exit 1

CMD ["node", "src/server.js"]
