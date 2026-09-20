import pytest
from pydantic import ValidationError

from app.schemas.onboarding import OnboardingShopCreate, SignupOtpRequest


def _signup_payload(password: str) -> dict:
    return {
        "owner_name": "Password Owner",
        "email": "password-owner@example.test",
        "shop_name": "Password Shop",
        "password": password,
    }


@pytest.mark.parametrize("password", ["short-1", "alllowercase12", "ONLYLETTERS!!!!"])
def test_signup_requires_a_long_password_with_three_character_classes(password):
    with pytest.raises(ValidationError):
        SignupOtpRequest(**_signup_payload(password))


def test_verified_signup_and_legacy_test_fixture_share_the_same_password_policy():
    password = "Strong-pass-2026"

    challenge = SignupOtpRequest(**_signup_payload(password))
    direct_fixture = OnboardingShopCreate(
        shop_name="Password Shop",
        owner_name="Password Owner",
        owner_email="password-owner@example.test",
        password=password,
    )

    assert challenge.password == password
    assert direct_fixture.password == password
