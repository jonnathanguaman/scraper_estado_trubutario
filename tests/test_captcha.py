from app.sri.captcha import (
    SRI_RECAPTCHA_ACTION,
    SRI_RECAPTCHA_MIN_SCORE,
    SRI_SITE_KEY,
    SRI_WEBSITE_URL,
    build_capsolver_task,
)


def test_capsolver_task_uses_recaptcha_enterprise_v3() -> None:
    task = build_capsolver_task()

    assert task == {
        "type": "ReCaptchaV3EnterpriseTaskProxyless",
        "websiteURL": SRI_WEBSITE_URL,
        "websiteKey": SRI_SITE_KEY,
        "pageAction": SRI_RECAPTCHA_ACTION,
        "minScore": SRI_RECAPTCHA_MIN_SCORE,
    }


def test_capsolver_task_can_include_anchor_and_reload_payloads() -> None:
    task = build_capsolver_task(anchor="anchor-payload", reload="reload-payload")

    assert task["anchor"] == "anchor-payload"
    assert task["reload"] == "reload-payload"
