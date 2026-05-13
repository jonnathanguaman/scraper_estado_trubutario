import pytest
from pydantic import ValidationError

from app.schemas import ConsultaRequest


def test_ruc_cedula_acepta_10_o_13_digitos() -> None:
    assert ConsultaRequest(identificacion="0102030405").identificacion == "0102030405"
    assert ConsultaRequest(identificacion="0102030405001").identificacion == "0102030405001"


def test_ruc_cedula_rechaza_texto() -> None:
    with pytest.raises(ValidationError):
        ConsultaRequest(identificacion="ABC123", tipo="ruc_cedula")


def test_pasaporte_acepta_alfanumerico() -> None:
    req = ConsultaRequest(identificacion="PA123456", tipo="pasaporte")
    assert req.identificacion == "PA123456"

