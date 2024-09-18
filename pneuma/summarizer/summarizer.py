import json
import logging
import math
import os
import sys
from pathlib import Path

import duckdb
import fire
import pandas as pd
import torch
from tqdm import tqdm

sys.path.append(str(Path(__file__).resolve().parent.parent))
from utils.logging_config import configure_logging
from utils.pipeline_initializer import initialize_pipeline
from utils.prompting_interface import prompt_pipeline
from utils.response import Response, ResponseStatus
from utils.storage_config import get_storage_path
from utils.summary_types import SummaryType
from utils.table_status import TableStatus

configure_logging()
logger = logging.getLogger("Summarizer")


class Summarizer:
    def __init__(
        self,
        db_path: str = os.path.join(get_storage_path(), "storage.db"),
        hf_token: str = "",
    ):
        self.db_path = db_path
        self.connection = duckdb.connect(db_path)

        # If we pass in the hf_token argument it causes
        # [WARNING] '>' not supported between instances of 'int' and 'str'
        # And the LLM won't generate output for some reason.
        # self.pipe = initialize_pipeline(
        #     "meta-llama/Meta-Llama-3-8B-Instruct", torch.bfloat16
        # )
        # Specific setting for Llama-3-8B-Instruct for batching
        # self.pipe.tokenizer.pad_token_id = self.pipe.model.config.eos_token_id
        # self.pipe.tokenizer.padding_side = "left"

        # Use small model for local testing
        # self.pipe = initialize_pipeline("TinyLlama/TinyLlama_v1.1", torch.bfloat16)
        # self.pipe.tokenizer.chat_template = "{% for message in messages %}{% if message['role'] == 'user' %}{{ ' ' }}{% endif %}{{ message['content'] }}{% if not loop.last %}{{ '  ' }}{% endif %}{% endfor %}{{ eos_token }}"
        # self.pipe.tokenizer.pad_token_id = self.pipe.model.config.eos_token_id
        # self.pipe.tokenizer.padding_side = "left"

    def summarize(self, table_id: str = None) -> str:
        if table_id is None or table_id == "":
            logger.info("Generating summaries for all unsummarized tables...")
            table_ids = [
                entry[0].replace("'", "''")
                for entry in self.connection.sql(
                    f"""SELECT id FROM table_status
                    WHERE status = '{TableStatus.REGISTERED}'"""
                ).fetchall()
            ]
            logger.info("Found %d unsummarized tables.", len(table_ids))
        else:
            table_ids = [table_id.replace("'", "''")]

        all_summary_ids = []
        for table_id in table_ids:
            logger.info("Summarizing table with ID: %s", table_id)
            all_summary_ids.extend(self.__summarize_table_by_id(table_id))

        return Response(
            status=ResponseStatus.SUCCESS,
            message=f"Total of {len(all_summary_ids)} summaries has been added "
            f"with IDs: {', '.join([str(summary_id) for summary_id in all_summary_ids])}.\n",
            data={"table_ids": table_ids, "summary_ids": all_summary_ids},
        ).to_json()

    def purge_tables(self) -> str:
        summarized_table_ids = [
            entry[0]
            for entry in self.connection.sql(
                f"SELECT id FROM table_status WHERE status = '{TableStatus.SUMMARIZED}'"
            ).fetchall()
        ]

        for table_id in summarized_table_ids:
            logger.info("Dropping table with ID: %s", table_id)
            # Escape single quotes to avoid breaking the SQL query
            table_id = table_id.replace("'", "''")
            self.connection.sql(f'DROP TABLE "{table_id}"')
            self.connection.sql(
                f"""UPDATE table_status
                SET status = '{TableStatus.DELETED}'
                WHERE id = '{table_id}'"""
            )

        return Response(
            status=ResponseStatus.SUCCESS,
            message=f"Total of {len(summarized_table_ids)} tables have been purged.\n",
        ).to_json()

    def __summarize_table_by_id(self, table_id: str) -> list[str]:
        status = self.connection.sql(
            f"SELECT status FROM table_status WHERE id = '{table_id}'"
        ).fetchone()[0]
        # if status == str(TableStatus.SUMMARIZED) or status == str(TableStatus.DELETED):
        #     logger.warning("Table with ID %s has already been summarized.", table_id)
        #     return []

        table_df = self.connection.sql(f"SELECT * FROM '{table_id}'").to_df()

        standard_summary = self.__generate_column_summary(table_df)
        narration_summaries = self.__generate_column_description(table_df)

        summary_ids = []

        standard_payload = json.dumps({"payload": standard_summary})
        standard_payload = standard_payload.replace("'", "''")
        summary_ids.append(
            self.connection.sql(
                f"""INSERT INTO table_summaries (table_id, summary, summary_type)
                VALUES ('{table_id}', '{standard_payload}', '{SummaryType.STANDARD}')
                RETURNING id"""
            ).fetchone()[0]
        )

        for narration_summary in narration_summaries:
            narration_payload = json.dumps({"payload": narration_summary})
            narration_payload = narration_payload.replace("'", "''")
            summary_ids.append(
                self.connection.sql(
                    f"""INSERT INTO table_summaries (table_id, summary, summary_type)
                    VALUES ('{table_id}', '{narration_payload}', '{SummaryType.NARRATION}')
                    RETURNING id"""
                ).fetchone()[0]
            )

        self.connection.sql(
            f"""UPDATE table_status
            SET status = '{TableStatus.SUMMARIZED}'
            WHERE id = '{table_id}'"""
        )

        return summary_ids

    def __generate_column_summary(self, df: pd.DataFrame) -> str:
        return " | ".join(df.columns).strip()

    def __generate_column_description(self, df: pd.DataFrame) -> list[str]:
        # Used for quick local testing
        # return " description | ".join(df.columns).strip() + " description"

        sample_size = math.ceil(min(len(df), 5))
        selected_df = df.sample(n=sample_size, random_state=0).reset_index(drop=True)

        formatted_rows = []
        for row_idx, row in selected_df.iterrows():
            formatted_row = " | ".join([f"{col}: {val}" for col, val in row.items()])
            formatted_rows.append(formatted_row.strip())

        return formatted_rows

    def __get_col_description_prompt(self, columns: str, column: str):
        return f"""A table has the following columns:
/*
{columns}
*/
Describe briefly what the {column} column represents. If not possible, simply state "No description.\""""


if __name__ == "__main__":
    fire.Fire(Summarizer)
