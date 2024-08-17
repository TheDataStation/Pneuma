import os
os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
os.environ["CUDA_VISIBLE_DEVICES"] = "0"
import setproctitle
setproctitle.setproctitle("python")

import pandas as pd
import torch
import ast

from utils.pipeline_initializer import initialize_pipeline
from utils.prompting_interface import prompt_pipeline
from tqdm import tqdm

pipe = initialize_pipeline("meta-llama/Meta-Llama-3-8B-Instruct", torch.bfloat16)
# Specific setting for Llama-3-8B-Instruct for batching
pipe.tokenizer.pad_token_id = pipe.model.config.eos_token_id
pipe.tokenizer.padding_side = 'left'

def get_prompt(context: str, question: str):
    return f"""Context:"{context}"

Question:"{question}"

The context describes a specific table that we have access to. Does this table answer the question? Begin your response with yes/no."""

bx1_name = "BX1_adventure"  # Adjust BX1 name
bx1 = pd.read_csv(f"{bx1_name}.csv")
bx1_corrected_name = f"{bx1_name}_corrected.csv"
contexts = pd.read_csv("contexts_adventure.csv")  # Adjust contexts name

questions_to_get_contexts = []
for i in range(len(bx1)):
    table = ast.literal_eval(bx1["answer_tables"][i])[0]
    context_id = bx1["context_id"][i]

    filtered_df = contexts[(contexts["table"] == table) & (contexts["id"] == context_id)].reset_index(drop=True)
    question = filtered_df["context_question"][0]
    questions_to_get_contexts.append(question)
bx1["question_to_get_context"] = questions_to_get_contexts

for i in tqdm(range(len(bx1))):
    question: str = bx1["question"][i]
    answer_tables: list[str] = ast.literal_eval(bx1["answer_tables"][i])
    dfd_q: str = bx1["question_to_get_context"][i]

    print(f"Processing row {i} of BX1")
    print(f"==> DFD Question: {dfd_q}")
    print(f"==> BX1 Question: {question}")

    filtered_contexts = contexts[contexts["context_question"] == dfd_q]

    conversations = []
    context_tables = []
    for j in filtered_contexts.index:
        context = filtered_contexts["context"][j]
        context_table = filtered_contexts["table"][j]

        prompt = get_prompt(context, question)
        conversations.append([{"role": "user", "content": prompt}])
        context_tables.append(context_table)
    
    for k in tqdm(range(0, len(conversations), 3)):
        outputs = prompt_pipeline(
            pipe, conversations[k:k+3], batch_size=3, context_length=8192, max_new_tokens=4, temperature=None, top_p=None
        )
        for output_idx, output in enumerate(outputs):
            answer: str = output[-1]["content"]
            if answer.strip().lower().startswith("yes") or answer.strip().lower().startswith("**yes"):
                answer_tables.append(context_tables[k+output_idx])

    answer_tables = sorted(list(set(answer_tables)))
    print(f"==> Answer tables: {answer_tables}")
    bx1.loc[i, "answer_tables"] = str(answer_tables)
    bx1.to_csv(bx1_corrected_name, index=False)  # Adjust name

print(f"FINAL: removing DFD questions from the DF")
bx1.drop("question_to_get_context", axis=1).to_csv(bx1_corrected_name, index=False)