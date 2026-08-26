from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    exito: bool = True
    code: int = 200
    token: str
    expira_en: str
