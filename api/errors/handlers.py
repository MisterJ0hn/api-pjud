import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.errors.exceptions import (
    CampoInvalidoError,
    ConflictoSincronizacionError,
    NoAutorizadoError,
    NoEncontradoError,
)

logger = logging.getLogger("pjud.api")


def _respuesta(code: int, mensaje: str) -> JSONResponse:
    return JSONResponse(status_code=code, content={"exito": False, "code": code, "mensaje": mensaje})


def _nombre_campo(error: dict) -> str:
    # error["loc"] es una tupla como ("body", "corte") o ("body", "rol") -- el ultimo
    # elemento es el nombre del campo que fallo la validacion de Pydantic.
    loc = error.get("loc") or ("campo",)
    return str(loc[-1])


def registrar_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(request: Request, exc: RequestValidationError):
        errores = exc.errors()
        campo = _nombre_campo(errores[0]) if errores else "desconocido"
        return _respuesta(400, f"Error en campo [{campo}]")

    @app.exception_handler(CampoInvalidoError)
    async def _handle_campo_invalido(request: Request, exc: CampoInvalidoError):
        return _respuesta(400, f"Error en campo [{exc.campo}]")

    @app.exception_handler(NoAutorizadoError)
    async def _handle_no_autorizado(request: Request, exc: NoAutorizadoError):
        return _respuesta(401, "No Autorizado")

    @app.exception_handler(ConflictoSincronizacionError)
    async def _handle_conflicto(request: Request, exc: ConflictoSincronizacionError):
        return _respuesta(409, "Conflicto")

    @app.exception_handler(NoEncontradoError)
    async def _handle_no_encontrado(request: Request, exc: NoEncontradoError):
        return _respuesta(404, "No encontrado")

    @app.exception_handler(Exception)
    async def _handle_error_no_controlado(request: Request, exc: Exception):
        logger.exception("Error no controlado en %s %s", request.method, request.url.path)
        return _respuesta(500, "Error interno")
