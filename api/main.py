from fastapi import FastAPI

from api.auth.router import router as auth_router
from api.civil.router import router as civil_router
from api.errors.handlers import registrar_exception_handlers
from api.logging_config import configurar_logger
from api.public_docs.router import router as public_docs_router

configurar_logger("pjud.api", "api.log")

app = FastAPI(title="PJUD API", version="1.0")

registrar_exception_handlers(app)

app.include_router(auth_router)
app.include_router(civil_router)
app.include_router(public_docs_router)


@app.get("/health")
async def health():
    return {"exito": True, "code": 200}
