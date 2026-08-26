# Despliegue en VPS (Docker Compose)

Instrucciones para levantar la API + worker + Postgres en un servidor nuevo usando
`docker-compose.yml`, `Dockerfile.api` y `Dockerfile.worker`.

## 1. Requisitos del VPS

- Linux (Ubuntu 22.04/24.04 recomendado), acceso root o sudo.
- Docker Engine + plugin Docker Compose:

  ```bash
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker $USER   # cerrar sesion y volver a entrar despues de esto
  ```

  Verificar:

  ```bash
  docker --version
  docker compose version
  ```

- Puerto 7092 libre (o el que definas via `API_PORT` en `.env`), y salida a
  internet para que el worker pueda llegar al sitio del PJUD.
- Al menos ~4 GB de disco libres (la imagen del worker incluye Chromium).

## 2. Copiar el proyecto al servidor

Desde tu maquina local, en la carpeta del proyecto:

```bash
rsync -avz --exclude .venv --exclude __pycache__ --exclude documentos \
  --exclude output --exclude logs \
  ./ usuario@IP_DEL_VPS:/opt/pjud/
```

(o `git clone` si el repo esta en un remoto). No hace falta copiar `.venv` — se
instala todo dentro de las imagenes Docker.

## 3. Configurar variables de entorno

En el servidor, dentro de `/opt/pjud/`:

```bash
cp .env.docker.example .env
nano .env
```

Ajustar como minimo:

- `POSTGRES_PASSWORD` — poner una clave real (no dejar el valor de ejemplo).
- `PUBLIC_BASE_URL` — dominio publico desde el que se serviran los PDF
  (ej. `https://api-pjud.temposoft.cl`), usado por el endpoint `/public/...`.
- `API_PORT` — puerto del host donde se publica la API (por defecto `7092`; el
  contenedor siempre escucha en `8000` puertas adentro).

Este `.env` es distinto al `.env` que usa el proyecto en modo local (ese tiene
`localhost` como host de Postgres); `docker-compose.yml` arma las URLs de conexion
apuntando al servicio `db` automaticamente, no lee el `.env` local.

## 4. Levantar el stack

```bash
cd /opt/pjud
docker compose up -d --build
```

Esto hace, en orden:

1. `db` — Postgres 16, espera a estar `healthy`.
2. `migrate` — corre `alembic upgrade head` una vez y termina.
3. `api` y `worker` — arrancan una vez que `migrate` termino OK.

El worker abre Chromium en modo "headed" contra un framebuffer virtual (`xvfb`),
porque el sitio del PJUD bloquea navegadores headless — es normal que no haya
ninguna ventana visible, todo corre dentro del contenedor.

## 5. Verificar que quedo arriba

```bash
docker compose ps
curl -s http://localhost:7092/health
```

Debe responder `{"exito":true,"code":200}`.

Logs en vivo:

```bash
docker compose logs -f api
docker compose logs -f worker
docker compose logs -f migrate   # solo util si la migracion fallo
```

Los logs tambien quedan en el volumen `logs` (`api.log`, `worker.log`), montado en
`/data/logs` dentro de cada contenedor.

## 6. Crear un cliente API y un usuario

No hay endpoint publico de registro (es a proposito, igual que una API key de
cualquier proveedor). Se usa `scripts/admin_cli.py` dentro del contenedor `api`:

```bash
# 1) crear el cliente (aplicacion que va a consumir la API) -- imprime el
#    x-client-key UNA sola vez, guardarlo ahi mismo
docker compose exec api python scripts/admin_cli.py crear-cliente "Portal Abogados"

# 2) crear un usuario para ese cliente (usar el <cliente_id> que imprimio el paso 1)
docker compose exec api python scripts/admin_cli.py crear-usuario <cliente_id> usuario@correo.cl "password-segura"
```

El usuario despues inicia sesion contra `POST /auth/login` (header `x-client-key`
+ body `email`/`password`) para obtener el bearer token con el que llama al resto
de la API.

## 7. Exponer con dominio + HTTPS (recomendado)

`docker-compose.yml` publica la API en `localhost:7092` del VPS. Para exponerla en
`PUBLIC_BASE_URL` con TLS, poner un reverse proxy delante (nginx, Caddy o similar)
que redirija `443 -> 127.0.0.1:7092` y maneje el certificado. Ejemplo minimo con
Caddy (`/etc/caddy/Caddyfile`):

```
api-pjud.temposoft.cl {
    reverse_proxy 127.0.0.1:7092
}
```

Caddy obtiene y renueva el certificado solo. Con nginx + certbot es el patron
habitual `proxy_pass http://127.0.0.1:8000;` + `certbot --nginx`.

## 8. Operacion diaria

- **Actualizar codigo:** `rsync` los cambios (o `git pull`) y luego:

  ```bash
  docker compose up -d --build
  ```

  (`migrate` vuelve a correr solo, `alembic upgrade head` es idempotente si no hay
  migraciones nuevas).

- **Reiniciar solo el worker** (por ejemplo si quedo colgado tras un timeout del
  sitio del PJUD):

  ```bash
  docker compose restart worker
  ```

- **Ver estado de la cola / causas:** conectarse a Postgres desde el host:

  ```bash
  docker compose exec db psql -U pjud -d pjud
  ```

- **Backup de la base de datos:**

  ```bash
  docker compose exec db pg_dump -U pjud pjud > backup_$(date +%F).sql
  ```

- **Apagar todo:**

  ```bash
  docker compose down          # mantiene los volumenes (db_data, documentos, logs)
  docker compose down -v       # ademas borra los volumenes -- CUIDADO, borra la BD
  ```

## 9. Troubleshooting

- **`db` falla en bucle con `could not write to file "postmaster.pid": Operation not
  permitted` o `.../pg_wal/xlogtemp...: Operation not permitted`:** pasa en VPS con
  kernel de CentOS/RHEL 7 (`3.10.0-...el7`, verificar con `docker info | grep
  "Kernel Version"`). Ese kernel trae miles de backports de Red Hat con numeracion
  de syscalls no estandar; el perfil `seccomp: builtin` de Docker filtra por numero
  asumiendo un kernel upstream normal, y termina bloqueando syscalls que Postgres
  necesita durante `initdb` (se ve como `Operation not permitted` en vez de un
  error de permisos real -- se confirma probando ownership/fallocate/truncate/flock
  a mano, que funcionan bien, mientras que Postgres sigue fallando). El
  `docker-compose.yml` ya trae el workaround (`security_opt: seccomp:unconfined`
  en `db` y `worker`). Si te encontraste con este error antes de tener ese cambio,
  hay que limpiar el volumen a medio inicializar y volver a levantar:

  ```bash
  docker compose down -v   # borra tambien db_data -- no hay datos que rescatar, initdb nunca termino
  docker compose up -d --build
  docker compose logs -f db
  ```

- **`migrate` falla y `api`/`worker` nunca arrancan:** revisar
  `docker compose logs migrate`; usualmente es la conexion a `db` o una migracion
  con error. `api` y `worker` dependen de que `migrate` termine con exito
  (`service_completed_successfully`), asi que no van a levantar hasta que se
  resuelva.

- **El worker tira `Timeout ... waiting for locator`:** el sitio del PJUD no
  respondio a tiempo o detecto el navegador. No es un problema de la
  configuracion Docker; el contenedor tiene `restart: unless-stopped` asi que
  reintenta solo. Si persiste, revisar `docker compose logs worker` para el
  error puntual.

- **Cambiaste la version de `playwright` en `requirements-api.txt`:** actualizar
  el tag de la imagen base en `Dockerfile.worker`
  (`mcr.microsoft.com/playwright/python:vX.Y.Z-jammy`) para que coincida, si no
  el navegador instalado puede no ser compatible con el driver de Python.
