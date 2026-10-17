# The Lineage web app. NEXT_PUBLIC_* values are baked in at build time.
FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_SHARED_DEMO
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_PUBLIC_SHARED_DEMO=$NEXT_PUBLIC_SHARED_DEMO NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build /app ./
CMD ["sh", "-c", "npx next start -H 0.0.0.0 -p ${PORT:-3000}"]
