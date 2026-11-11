"""Documentation and deployment files must agree with the code and must not contain secrets."""
from __future__ import annotations

import re

import yaml

from config import settings
from scripts import generate_docs as gd

ROOT = settings.PROJECT_ROOT


def test_generated_reference_docs_are_up_to_date():
    assert (ROOT / "docs" / "KPI_REFERENCE.md").read_text(encoding="utf-8") == gd.render_kpi_reference(), \
        "KPI definitions changed: run  python -m scripts.generate_docs"
    assert (ROOT / "docs" / "THRESHOLDS.md").read_text(encoding="utf-8") == gd.render_thresholds(), \
        "settings changed: run  python -m scripts.generate_docs"


def test_threshold_doc_lists_every_rule_constant():
    text = gd.render_thresholds()
    for name in ("SPARSE_MONTH_FRACTION", "SELLER_MIN_ORDERS", "COHORT_MIN_SIZE", "ML_RANDOM_STATE", "FORECAST_MIN_MONTHS"):
        assert f"`{name}`" in text


def _app_pages() -> list[tuple[str, str]]:
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    return re.findall(r'st\.Page\("pages/([a-z_]+)\.py", title="([^"]+)"', src)


def test_every_page_file_is_in_the_navigation_and_the_readme():
    pages = _app_pages()
    files = {p.stem for p in (ROOT / "pages").glob("*.py") if p.stem != "__init__"}
    assert {f for f, _ in pages} == files, "a page file is not registered in app.py (or vice versa)"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    missing = [title for _, title in pages if title not in readme]
    assert not missing, f"pages missing from README: {missing}"


def test_readme_states_the_historical_limitation_and_not_profit():
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    assert "2016" in readme and "not profit" in readme and "inventory" in readme


def test_compose_file_has_no_hardcoded_secrets():
    c = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    for name, svc in c["services"].items():
        for key, val in (svc.get("environment") or {}).items():
            if "PASSWORD" in key:
                assert "${DB_PASSWORD" in str(val) and ":?" in str(val), f"{name}.{key} must come from .env and be required"
    assert "ports" not in c["services"]["db"], "database must not be published to the host by default"
    assert c["services"]["app"]["ports"][0].startswith("127.0.0.1:")


def test_docker_files_keep_secrets_and_data_out_of_the_image():
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignore and "data/raw/*" in ignore
    docker = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^USER\s+\w+", docker, re.M) and "HEALTHCHECK" in docker
    assert "PASSWORD" not in docker.upper().replace("DB_PASSWORD", "")


def test_gitignore_excludes_env_and_raw_data():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in lines and "data/raw/*" in lines


def test_no_credentials_in_source_files():
    pat = re.compile(r"""(password|passwd|secret|api_key)\s*=\s*["'][^"'\s]{4,}["']""", re.I)
    allowed = {"your_password", "ci_only_password"}
    offenders = []
    for path in list(ROOT.glob("**/*.py")) + list(ROOT.glob("**/*.yml")) + list(ROOT.glob("**/*.yaml")):
        if any(part in {".venv", "venv", ".git", "__pycache__"} for part in path.parts):
            continue
        for m in pat.finditer(path.read_text(encoding="utf-8", errors="ignore")):
            if m.group(0).split("=")[1].strip(" \"'") not in allowed:
                offenders.append(f"{path.relative_to(ROOT)}: {m.group(0)}")
    assert not offenders, offenders


def test_env_example_has_only_placeholders():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "DB_PASSWORD=your_password" in text
