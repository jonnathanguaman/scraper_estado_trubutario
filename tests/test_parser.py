from app.sri.parser import parse_html


def test_parsea_resumen_desde_html() -> None:
    html = """
    <html><body>
      <section>
        <h3>Permiso de facturacion</h3>
        <span>Vigencia</span>
        <strong>12 meses</strong>
      </section>
      <section>
        <h3>Estado tributario</h3>
        <span>Resultado</span>
        <strong>AL DIA EN SUS OBLIGACIONES</strong>
      </section>
    </body></html>
    """

    data = parse_html(html)

    assert data.permiso_facturacion.vigencia == "12 meses"
    assert data.estado_tributario.resultado == "AL DIA EN SUS OBLIGACIONES"


def test_fusiona_respuestas_api_capturadas() -> None:
    data = parse_html(
        "<html><body></body></html>",
        {
            "estado_tributario": {
                "textoEstadoTributario": "AL DIA EN SUS OBLIGACIONES",
            },
            "permiso_facturacion": {"permisoFacturacion": "TOTAL"},
        },
    )

    assert data.estado_tributario.resultado == "AL DIA EN SUS OBLIGACIONES"
    assert data.permiso_facturacion.vigencia == "12 meses"
