import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from registration.registration import Registration

DB_PATH = "../out/storage.db"


def read_benchmark_data(registration: Registration):
    registration.read_folder("../../data_src/tables/chicago_open_data", "sample_user")


def read_sample_data(registration: Registration):
    registration.read_table("../sample_data/csv/5cq6-qygt.csv", "sample_user")
    registration.read_table("../sample_data/csv/5n77-2d6a.csv", "sample_user")

    registration.add_context(
        "../sample_data/csv/5cq6-qygt.csv", "../sample_data/context/sample_context.txt"
    )
    registration.add_context(
        "../sample_data/csv/5n77-2d6a.csv", "../sample_data/context/sample_context.txt"
    )

    registration.add_summary(
        "../sample_data/csv/5cq6-qygt.csv", "../sample_data/summary/sample_summary.txt"
    )
    registration.add_summary(
        "../sample_data/csv/5n77-2d6a.csv", "../sample_data/summary/sample_summary.txt"
    )


if __name__ == "__main__":
    os.makedirs("../out", exist_ok=True)
    registration = Registration(DB_PATH)
    registration.setup()

    read_sample_data(registration)
