FROM node:20-alpine

WORKDIR /app

# Install dependencies for native modules
RUN apk add --no-cache python3 make g++

COPY package*.json ./
RUN npm ci --only=production

COPY . .

RUN mkdir -p uploads/documents uploads/submissions

EXPOSE 5000

CMD ["node", "src/index.js"]
