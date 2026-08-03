"""Shared editable X-Security product context used by agent prompts."""
from pathlib import Path

PROMPT_PATH = Path(__file__).resolve().parent / "data" / "prompt_file.txt"


def read_product_context() -> str:
    if not PROMPT_PATH.exists():
        return "X-Security is a B2B endpoint-security and antivirus product."
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def save_product_context(content: str) -> str:
    value = content.strip()
    if not value:
        raise ValueError("Product context cannot be empty.")
    if len(value) > 12000:
        raise ValueError("Keep product context under 12,000 characters.")
    PROMPT_PATH.write_text(value + "\n", encoding="utf-8")
    return value
