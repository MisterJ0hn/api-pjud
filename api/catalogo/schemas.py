from pydantic import BaseModel


class TribunalItem(BaseModel):
    id: int
    nombre: str


class CorteItem(BaseModel):
    id: int
    nombre: str
    tribunales: list[TribunalItem]


class CatalogoTribunalesResponse(BaseModel):
    cortes: list[CorteItem]
