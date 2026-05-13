from app.sri.parser import parse_html


def test_parsea_campos_generales_desde_html() -> None:
    html = """
    <html><body>
      <div><span>Identificación</span><br><span>1700000000001</span></div>
      <div><span>Nombre/Razón social</span><br><span>EMPRESA DEMO S.A.</span></div>
      <h2>AL DÍA EN SUS OBLIGACIONES</h2>
    </body></html>
    """

    data = parse_html(html)

    assert data.identificacion == "1700000000001"
    assert data.nombre_razon_social == "EMPRESA DEMO S.A."
    assert data.estado_tributario == "AL DÍA EN SUS OBLIGACIONES"


def test_fusiona_respuestas_api_capturadas() -> None:
    data = parse_html(
        "<html><body></body></html>",
        {
            "persona": {"identificacion": "1700000000001", "nombreCompleto": "PERSONA DEMO"},
            "estado_tributario": {
                "textoEstadoTributario": "AL DÍA EN SUS OBLIGACIONES",
                "dtObligacionesPendientesPresentacion": [{"obligacion": "IVA"}],
            },
            "permiso_facturacion": {"permisoFacturacion": "TOTAL"},
        },
    )

    assert data.identificacion == "1700000000001"
    assert data.nombre_razon_social == "PERSONA DEMO"
    assert data.estado_tributario == "AL DÍA EN SUS OBLIGACIONES"
    assert data.permiso_facturacion == "TOTAL"
    assert data.obligaciones_presentacion == [{"obligacion": "IVA"}]

