import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def env_example_names() -> set[str]:
    lines = (ROOT / ".env.example").read_text().splitlines()
    return {line.split("=", 1)[0] for line in lines if re.match(r"^[A-Z0-9_]+=", line)}


def test_env_example_is_the_canonical_list_of_the_five_secrets() -> None:
    assert env_example_names() == {
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_OWNER_ID",
        "HIKERAPI_KEY",
        "GROQ_API_KEY",
        "DEEPSEEK_API_KEY",
    }


def test_setup_wizard_sets_every_canonical_secret_and_nothing_else() -> None:
    wizard = (ROOT / "scripts" / "setup-wizard.sh").read_text()
    stages = wizard.split("run_wizard() {", 1)[1]
    assert set(re.findall(r"set_secret ([A-Z0-9_]+)", stages)) == env_example_names()


def test_workflows_only_reference_canonical_secrets() -> None:
    referenced = {
        name
        for workflow in (ROOT / ".github" / "workflows").iterdir()
        if workflow.suffix in {".yml", ".yaml"}
        for name in re.findall(r"secrets\.([A-Za-z0-9_]+)", workflow.read_text())
    }
    assert referenced - {"GITHUB_TOKEN"} <= env_example_names()
