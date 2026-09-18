import re
import tomllib
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]


def test_fastmcp_is_pinned_exactly_in_project_metadata():
    project = tomllib.loads((SERVICE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    fastmcp_dependencies = [
        dependency
        for dependency in project["project"]["dependencies"]
        if dependency.lower().startswith("fastmcp")
    ]

    assert fastmcp_dependencies == ["fastmcp==4.0.3"]


def test_container_installs_the_nutrition_project_instead_of_direct_fastmcp():
    instructions = [
        line.strip()
        for line in (SERVICE_ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    project_install = "RUN pip install ."
    assert project_install in instructions
    assert instructions.index("WORKDIR /srv/services/nutrition") < instructions.index(
        project_install
    )
    assert "COPY services/nutrition/pyproject.toml ./pyproject.toml" in instructions
    assert "COPY services/nutrition/app ./app" in instructions

    direct_fastmcp_installs = [
        instruction
        for instruction in instructions
        if instruction.startswith("RUN pip install")
        and re.search(r"(?<![\w-])fastmcp(?![\w-])", instruction, re.IGNORECASE)
    ]
    assert direct_fastmcp_installs == []
