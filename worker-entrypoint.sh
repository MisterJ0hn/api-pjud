#!/bin/sh
# Reemplaza a xvfb-run: ese script sincroniza con Xvfb via la señal SIGUSR1
# (trap USR1 + wait), y ese mecanismo se cuelga de forma silenciosa dentro de
# Docker sin un init real como PID 1 -- Xvfb queda arriba pero el comando
# nunca se llega a ejecutar. Acá arrancamos Xvfb a mano y esperamos a que
# aparezca el socket del display en vez de depender de la señal.
set -e

DISPLAY_NUM=99

Xvfb ":${DISPLAY_NUM}" -screen 0 1280x1024x24 -nolisten tcp &

for i in $(seq 1 50); do
    [ -e "/tmp/.X11-unix/X${DISPLAY_NUM}" ] && break
    sleep 0.1
done

export DISPLAY=":${DISPLAY_NUM}"

exec "$@"
