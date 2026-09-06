FROM node:22-alpine

WORKDIR /app

COPY package*.json ./

# The Docker workflow and handoff docs use pnpm for test/build commands.
# Install it explicitly so the official Node entrypoint does not interpret
# `pnpm` as a JavaScript file when the binary is missing.
RUN npm install -g pnpm@10.15.0 \
    && npm install

COPY . .

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
