#!/bin/sh
# Reemplaza a xvfb-run: ese script sincroniza con Xvfb via la señal SIGUSR1
# (trap USR1 + wait), y ese mecanismo se cuelga de forma silenciosa dentro de
# Docker sin un init real como PID 1 -- Xvfb queda arriba pero el comando
# nunca se llega a ejecutar. Acá arrancamos Xvfb a mano y esperamos a que
# aparezca el socket del display en vez de depender de la señal.
set -e

DISPLAY_NUM=99

# La capa de escritura del contenedor sobrevive a `docker restart`. Si el proceso
# anterior murió sin limpiar, quedan /tmp/.X99-lock y /tmp/.X11-unix/X99: Xvfb ve
# "Server is already active for display 99" y aborta, y el chequeo del socket de
# más abajo daría un falso positivo con el socket viejo. Los borramos siempre --
# como somos el único dueño del display :99, nunca hay un Xvfb legítimo vivo acá.
rm -f "/tmp/.X${DISPLAY_NUM}-lock" "/tmp/.X11-unix/X${DISPLAY_NUM}"

Xvfb ":${DISPLAY_NUM}" -screen 0 1280x1024x24 -nolisten tcp &
XVFB_PID=$!

for i in $(seq 1 50); do
    # Xvfb ya murió (lock stale, binario ausente, etc.): abortar en vez de seguir
    # a `exec` y lanzar Chromium en modo headed sin display.
    if ! kill -0 "$XVFB_PID" 2>/dev/null; then
        echo "worker-entrypoint: Xvfb (:${DISPLAY_NUM}) no arrancó; abortando." >&2
        wait "$XVFB_PID" 2>/dev/null || true
        exit 1
    fi
    [ -e "/tmp/.X11-unix/X${DISPLAY_NUM}" ] && break
    sleep 0.1
done

if [ ! -e "/tmp/.X11-unix/X${DISPLAY_NUM}" ]; then
    echo "worker-entrypoint: timeout esperando el socket de Xvfb (:${DISPLAY_NUM}); abortando." >&2
    kill "$XVFB_PID" 2>/dev/null || true
    exit 1
fi

export DISPLAY=":${DISPLAY_NUM}"

exec "$@"
