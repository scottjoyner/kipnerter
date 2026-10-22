FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ARG KIPNERTER_RELEASE_SHA
ENV KIPNERTER_RELEASE_SHA=${KIPNERTER_RELEASE_SHA}
ENV NODE_ENV=production
COPY --from=build /app .
EXPOSE 3000
CMD ["npm", "start"]
