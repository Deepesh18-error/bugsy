FROM node:22-alpine
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY server.mjs ./
COPY document_state.mjs ./
USER node
EXPOSE 1234
CMD ["npm", "start"]
