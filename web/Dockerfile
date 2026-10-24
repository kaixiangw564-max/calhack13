# PlainPath accessible website (Next.js). Build context: web/.
FROM node:22-slim

ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

ENV NODE_ENV=production
EXPOSE 8080
CMD ["npx", "next", "start", "-p", "8080"]
