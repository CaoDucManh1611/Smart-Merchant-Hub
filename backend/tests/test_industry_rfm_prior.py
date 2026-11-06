from app.services import industry_rfm_prior


def test_relative_module_file_and_changed_cwd_keep_prior_artifact_path(monkeypatch, tmp_path):
    expected_path = industry_rfm_prior._artifact_path()
    assert expected_path.is_file()

    # Linux pytest/import configurations can retain a relative module __file__.
    # Simulate that and a test/worker changing CWD after module import.
    monkeypatch.setattr(industry_rfm_prior, "__file__", "app/services/industry_rfm_prior.py")
    monkeypatch.chdir(tmp_path)

    assert industry_rfm_prior._artifact_path() == expected_path
    industry_rfm_prior.load_industry_rfm_prior.cache_clear()
    try:
        assert industry_rfm_prior.load_industry_rfm_prior()["model_version"] == (
            industry_rfm_prior.INDUSTRY_RFM_PRIOR_VERSION
        )
    finally:
        industry_rfm_prior.load_industry_rfm_prior.cache_clear()
