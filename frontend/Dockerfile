# Etapa 1: Construcción de la aplicación Angular
FROM cgr.dev/chainguard/node:latest AS build

WORKDIR /app

# Copiar solo los archivos de dependencias primero (para aprovechar el caché de Docker)
COPY --chown=node:node package.json package-lock.json ./

# Instalar las dependencias (incluye devDependencies para el build)
RUN npm ci

# Copiar el resto de los archivos del proyecto
COPY --chown=node:node . .

# Construir la aplicación Angular para producción
RUN npm run build

# Etapa 2: Nginx sirve el SPA y hace de proxy de /api hacia el backend
FROM cgr.dev/chainguard/nginx:latest

COPY --from=build /app/dist/frontend/browser /usr/share/nginx/html
COPY ./nginx.conf /etc/nginx/nginx.conf

EXPOSE 8080
