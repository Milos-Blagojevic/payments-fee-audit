"""The data of the site's extraction page, `site/static/extract/extraction.json` (offline, free).

The page runs the extraction in a visitor's browser through Puter (docs/llm-extraction.md, "In the browser"). What it
sends to the model and checks the answer against comes from this file, written from the same code and files as
`extract`: the prompt as `prompt()` assembles it, the structured-output schema, the full contract schema, the model
settings from config/llm.yml, and the five sample contract versions with their hand-written YAML and recorded cost.
"""

import json
from pathlib import Path

from feeaudit.contracts import SCHEMA_PATH
from feeaudit.extraction.budget import CONFIG_PATH, load_config
from feeaudit.extraction.extract import (OUT_DIR, RECORDED, TASKS, TEXT_DIR, YAML_NOTICE, extraction_schema, prompt,
                                         source_files)

EXPORT_PATH = Path("site/static/extract/extraction.json")
PROVIDERS_DIR = Path("contracts/providers")


def _recorded(path):
    if not path.exists():
        return None
    record = json.loads(path.read_text())
    return {"model": record["model"], "timestamp": record["timestamp"], "cost_usd": record["cost_usd"],
            "input_tokens": record["usage"]["input_tokens"], "output_tokens": record["usage"]["output_tokens"]}


def export_data(root=Path(".")):
    """The page's data for the repository at `root`; paths in it are relative to `root`."""
    root = Path(root)
    config = load_config(root / CONFIG_PATH)
    samples = []
    for name in sorted(p.stem for p in (root / TEXT_DIR).glob("*.md")):
        files = [(role, path.relative_to(root)) for role, path in source_files(name, root / TEXT_DIR)]
        documents = [(role, (root / path).read_text()) for role, path in files]
        hand_written = PROVIDERS_DIR / f"{name}.yml"
        samples.append({
            "name": name,
            "documents": [{"role": role, "path": path.as_posix(), "text": text}
                          for (role, path), (_, text) in zip(files, documents)],
            # As build_request() sends them; the page builds the same from `documents` and `tasks` (tests/js).
            "messages": prompt(documents)["messages"],
            "hand_written": {"path": hand_written.as_posix(), "yaml": (root / hand_written).read_text()},
            "recorded": _recorded(root / OUT_DIR / RECORDED / f"{name}.json"),
        })
    return {
        "generated_by": "python -m feeaudit.extraction export",
        "model": config.default_model,
        "max_tokens": config.max_tokens,
        "effort": config.effort,
        "system": prompt([(d["role"], d["text"]) for d in samples[0]["documents"]])["system"],
        "tasks": dict(TASKS),
        "extraction_schema": extraction_schema(),
        "contract_schema": json.loads(SCHEMA_PATH.read_text()),
        "yaml_notice": list(YAML_NOTICE),
        "samples": samples,
    }


def render_export(root=Path(".")):
    return json.dumps(export_data(root), indent=1, ensure_ascii=False) + "\n"
