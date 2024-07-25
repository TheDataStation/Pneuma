import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from registration.registration import Registration

DB_PATH = "../out/storage.db"

if __name__ == "__main__":
    os.makedirs("../out", exist_ok=True)
    registration = Registration(DB_PATH)
    registration.setup()
    registration.read_table("../sample_data/5cq6-qygt.csv", "david")
    registration.read_table("../sample_data/5n77-2d6a.csv", "david")

    registration.add_context(
        "../sample_data/5cq6-qygt.csv", "../sample_data/sample_context.txt"
    )
    registration.add_context(
        "../sample_data/5n77-2d6a.csv", "../sample_data/sample_context.txt"
    )

    registration.add_summary(
        "../sample_data/5cq6-qygt.csv", "../sample_data/sample_summary.txt"
    )
    registration.add_summary(
        "../sample_data/5n77-2d6a.csv", "../sample_data/sample_summary.txt"
    )