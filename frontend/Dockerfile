FROM node:20-alpine AS builder

WORKDIR /app
COPY package*.json ./
RUN npm ci

COPY . .

ARG VITE_SCHOOL_NAME="My School"
ARG VITE_API_URL="/api"
ENV VITE_SCHOOL_NAME=$VITE_SCHOOL_NAME
ENV VITE_API_URL=$VITE_API_URL

RUN npm run build

# Production stage - serve with Nginx
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx-frontend.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
