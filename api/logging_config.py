import logging
import os
from logging.handlers import RotatingFileHandler

from api.config import settings


def configurar_logger(nombre: str, archivo: str) -> logging.Logger:
    logger = logging.getLogger(nombre)
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    # Sin esto, "pjud.worker.callback" (que tiene sus handlers) propaga a "pjud.worker" (que
    # tambien los tiene) y cada linea sale dos veces.
    logger.propagate = False
    formato = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

    ruta = os.path.join(settings.log_dir, archivo)
    file_handler = RotatingFileHandler(ruta, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formato)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formato)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger
