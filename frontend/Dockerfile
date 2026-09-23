FROM node:22-alpine AS development

WORKDIR /app

COPY package*.json ./

# The Docker workflow and handoff docs use pnpm for test/build commands.
# Install it explicitly so the official Node entrypoint does not interpret
# `pnpm` as a JavaScript file when the binary is missing.
RUN npm install -g pnpm@10.15.0 \
    && npm install

COPY . .

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

FROM node:22-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS production

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=3s --retries=6 CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
