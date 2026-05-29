from app.sri.scraper import SriScraper
from app.schemas import ConsultaRequest


def test_captcha_error_message_extracts_nested_sri_message() -> None:
    scraper = SriScraper(browser=None, settings=None)  # type: ignore[arg-type]

    message = scraper._captcha_error_message(
        {
            "captcha_validation_error": {
                "status": 400,
                "body": '{"mensaje":"{\\"mensaje\\":\\"Puntaje bajo: 0.0 (umbral=0.5)\\"}"}',
            }
        }
    )

    assert message == "El SRI rechazo el token reCAPTCHA: Puntaje bajo: 0.0 (umbral=0.5)"


def test_classify_response_does_not_hide_captcha_error_message() -> None:
    scraper = SriScraper(browser=None, settings=None)  # type: ignore[arg-type]

    message = scraper._captcha_error_message(
        {
            "captcha_validation_error": {
                "status": 400,
            }
        }
    )

    assert message == "El SRI rechazo el token reCAPTCHA. HTTP 400."


async def test_build_response_does_not_parse_data_when_captcha_required() -> None:
    class FakePage:
        async def content(self) -> str:
            return "<html><body>AL DIA EN SUS OBLIGACIONES</body></html>"

    scraper = SriScraper(browser=None, settings=None)  # type: ignore[arg-type]
    response = await scraper._build_response(
        page=FakePage(),  # type: ignore[arg-type]
        request=ConsultaRequest(identificacion="0301652509001", return_html=True, return_data=True),
        network_payloads={
            "captcha_validation_error": {
                "status": 400,
                "body": '{"mensaje":"{\\"mensaje\\":\\"Puntaje bajo: 0.0 (umbral=0.5)\\"}"}',
            }
        },
        status="captcha_required",
        masked_id="***9001",
        started_at=0.0,
    )

    assert response.status == "captcha_required"
    assert response.data is None
    assert response.html is not None
