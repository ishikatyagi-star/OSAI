FROM node:24-alpine

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .

# Drop root: the node image ships an unprivileged `node` user.
RUN chown -R node:node /app
USER node

EXPOSE 3000
