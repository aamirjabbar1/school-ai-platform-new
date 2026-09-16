# Node 22: the classroom dependencies pull in a transitive package that
# declares `engines: node >=22.22`, which yarn enforces — a Node 20 builder
# fails the install outright.
FROM node:22-alpine AS builder

WORKDIR /app

# Enable Corepack so yarn is available without a separate install step
RUN corepack enable

COPY package.json yarn.lock* ./
RUN yarn install --frozen-lockfile

COPY . .

ARG VITE_SCHOOL_NAME="My School"
ARG VITE_API_URL="/api"
ENV VITE_SCHOOL_NAME=$VITE_SCHOOL_NAME
ENV VITE_API_URL=$VITE_API_URL

RUN yarn build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx-frontend.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
