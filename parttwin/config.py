from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "parttwin.db"

STAGES = [
    "UNDERSTAND",
    "SEARCH",
    "CHECK",
    "COMPARE",
    "INVESTIGATE",
    "RISK ASSESSMENT",
    "EVIDENCE",
    "RECOMMEND",
    "ENGINEER APPROVAL",
    "KNOWLEDGE VAULT",
]

# Dimensions: soft constraint. Exceeding this delta (mm) requires physical verification.
DIMENSION_VERIFY_MM = 3.0
DIMENSION_HIGH_RISK_MM = 15.0

SEMANTIC_TOP_K = 12
