import setproctitle

setproctitle.setproctitle("/usr/bin/python")
import os
import torch
import time
import sys
import chromadb
import bm25s
import Stemmer
import numpy as np

sys.path.append("..")

from tqdm import tqdm
from transformers import set_seed
from FlagEmbedding import FlagLLMReranker
from chromadb.api.models.Collection import Collection
from benchmark_generator.context.utils.jsonl import read_jsonl, write_jsonl
from benchmark_generator.context.utils.pipeline_initializer import initialize_pipeline
from hybrid_retriever import HybridRetriever, RerankingMode


os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
os.environ["CUDA_VISIBLE_DEVICES"] = "0"
set_seed(42, deterministic=True)

stemmer = Stemmer.Stemmer("english")

reranker = None
reranking_mode = RerankingMode.NONE
# reranker = initialize_pipeline("../../models/llama", torch.bfloat16)
# reranking_mode = RerankingMode.LLM
# reranker = FlagLLMReranker("../../models/bge-reranker")
# reranking_mode = RerankingMode.DIRECT_SCORE
hybrid_retriever = HybridRetriever(reranker, reranking_mode)

hitrates_data: list[dict[str, str]] = []


def indexing_keyword(
    stemmer,
    narration_contents: list[dict[str, str]],
    contexts: list[dict[str, str]] = None,
):
    corpus_json = []
    tables = sorted({content["table"] for content in narration_contents})
    for table in tables:
        cols_descriptions = [
            content["summary"]
            for content in narration_contents
            if content["table"] == table
        ]
        for content_idx, content in enumerate(cols_descriptions):
            corpus_json.append(
                {
                    "text": content,
                    "metadata": {"table": f"{table}_SEP_contents_{content_idx}"},
                }
            )

        if contexts is not None:
            filtered_contexts = [
                context["context"] for context in contexts if context["table"] == table
            ]
            for context_idx, context in enumerate(filtered_contexts):
                corpus_json.append(
                    {
                        "text": context,
                        "metadata": {"table": f"{table}_SEP_{context_idx}"},
                    }
                )

    corpus_text = [doc["text"] for doc in corpus_json]
    corpus_tokens = bm25s.tokenize(
        corpus_text, stopwords="en", stemmer=stemmer, show_progress=False
    )

    retriever = bm25s.BM25(corpus=corpus_json)
    retriever.index(corpus_tokens, show_progress=False)
    return retriever


def get_question_key(benchmark_type: str, use_rephrased_questions: bool):
    if benchmark_type == "content":
        if not use_rephrased_questions:
            question_key = "question_from_sql_1"
        else:
            question_key = "question"
    else:
        if not use_rephrased_questions:
            question_key = "question_bx1"
        else:
            question_key = "question_bx2"
    return question_key


def evaluate_benchmark(
    benchmark: list[dict[str, str]],
    benchmark_type: str,
    k: int,
    collection: Collection,
    retriever,
    stemmer,
    dataset: str,
    n=3,
    alpha=0.5,
    use_rephrased_questions=False,
):
    start = time.time()
    hitrate_sum = 0
    wrong_questions = []
    increased_k = k * n
    question_key = get_question_key(benchmark_type, use_rephrased_questions)

    questions = []
    for data in benchmark:
        questions.append(data[question_key])
    embed_questions = np.loadtxt(
        f"../embeddings/embed-{dataset}-questions-{benchmark_type}-{use_rephrased_questions}.txt"
    )
    embed_questions = [embed.tolist() for embed in embed_questions]

    for idx, datum in enumerate(tqdm(benchmark)):
        answer_tables = datum["answer_tables"]
        question_embedding = embed_questions[idx]

        query_tokens = bm25s.tokenize(
            questions[idx], stemmer=stemmer, show_progress=False
        )

        results, scores = retriever.retrieve(
            query_tokens, k=increased_k, show_progress=False
        )
        bm25_res = (results, scores)
        vec_res = collection.query(
            query_embeddings=[question_embedding], n_results=increased_k
        )

        all_nodes = hybrid_retriever.retrieve(
            bm25_res, vec_res, increased_k, questions[idx], alpha
        )
        before = hitrate_sum
        for table, _, _ in all_nodes[:k]:
            table = table.split("_SEP_")[0]
            if table in answer_tables:
                hitrate_sum += 1
                break
        if before == hitrate_sum:
            wrong_questions.append(idx)
        # Checkpoint
        if idx % 100 == 0:
            print(f"Current Hit Rate Sum at index {idx}: {hitrate_sum}")
            print(
                f"Current wrongly answered questions at index {idx}: {wrong_questions}"
            )

    end = time.time()
    print(
        f"Hit Rate (k={k};n={n};alpha={alpha}): {round(hitrate_sum/len(benchmark) * 100, 2)}"
    )
    print(f"Benchmarking Time: {end - start} seconds")
    print(f"Wrongly answered questions: {wrong_questions}")
    hitrates_data.append(
        {
            "dataset": dataset,
            "k": k,
            "n": n,
            "alpha": alpha,
            "hitrate": round(hitrate_sum / len(benchmark) * 100, 2),
            "wrong_questions": wrong_questions,
        }
    )
    write_jsonl(hitrates_data, f"hybrid-{reranking_mode}-{k}.jsonl")


def start(
    dataset: str,
    rows: list[dict[str, str]],
    narrations: list[dict[str, str]],
    contexts: list[dict[str, str]],
    content_benchmark: list[dict[str, str]],
    context_benchmark: list[dict[str, str]],
    alphas: list[int],
    ns: list[int],
    k=1,
):
    print(f"Processing {dataset} dataset")
    start = time.time()
    client = chromadb.PersistentClient(f"../indices/index-{dataset}-pneuma-summarizer")
    collection = client.get_collection("benchmark")
    retriever = indexing_keyword(stemmer, rows + narrations, contexts)
    end = time.time()
    print(f"Indexing time: {end-start} seconds")

    for alpha in alphas:
        for n in ns:
            print(f"BC1 (k = {k}) with alpha={alpha} n={n}")
            evaluate_benchmark(
                benchmark=content_benchmark,
                benchmark_type="content",
                k=k,
                collection=collection,
                retriever=retriever,
                stemmer=stemmer,
                dataset=dataset,
                n=n,
                alpha=alpha,
                use_rephrased_questions=False,
            )
            print("=" * 50)

            print(f"BC2 (k = {k}) with alpha={alpha} n={n}")
            evaluate_benchmark(
                benchmark=content_benchmark,
                benchmark_type="content",
                k=k,
                collection=collection,
                retriever=retriever,
                stemmer=stemmer,
                dataset=dataset,
                n=n,
                alpha=alpha,
                use_rephrased_questions=True,
            )
            print("=" * 50)

            print(f"BX1 (k = {k}) with alpha={alpha} n={n}")
            evaluate_benchmark(
                benchmark=context_benchmark,
                benchmark_type="context",
                k=k,
                collection=collection,
                retriever=retriever,
                stemmer=stemmer,
                dataset=dataset,
                n=n,
                alpha=alpha,
                use_rephrased_questions=False,
            )
            print("=" * 50)

            print(f"BX2 (k = {k}) with alpha={alpha} n={n}")
            evaluate_benchmark(
                benchmark=context_benchmark,
                benchmark_type="context",
                k=k,
                collection=collection,
                retriever=retriever,
                stemmer=stemmer,
                dataset=dataset,
                n=n,
                alpha=alpha,
                use_rephrased_questions=True,
            )
            print("=" * 50)


if __name__ == "__main__":
    # Adjust
    ns = [5]
    alphas = [0.7]
    k = 10

    dataset = "fetaqa"
    narrations = read_jsonl(
        f"../../pneuma_summarizer/summaries/narrations/{dataset}.jsonl"
    )
    rows = read_jsonl(f"../../pneuma_summarizer/summaries/rows/{dataset}.jsonl")
    content_benchmark = read_jsonl(
        "../../data_src/benchmarks/content/pneuma_fetaqa_questions_annotated.jsonl"
    )
    context_benchmark = read_jsonl(
        f"../../data_src/benchmarks/context/{dataset}/bx_{dataset}.jsonl"
    )
    contexts = read_jsonl(
        f"../../data_src/benchmarks/context/{dataset}/contexts_{dataset}.jsonl"
    )
    start(
        dataset,
        rows,
        narrations,
        contexts,
        content_benchmark,
        context_benchmark,
        alphas,
        ns,
        k
    )

    dataset = "chicago"
    narrations = read_jsonl(
        f"../../pneuma_summarizer/summaries/narrations/{dataset}.jsonl"
    )
    rows = read_jsonl(f"../../pneuma_summarizer/summaries/rows/{dataset}.jsonl")
    content_benchmark = read_jsonl(
        "../../data_src/benchmarks/content/pneuma_chicago_10K_questions_annotated.jsonl"
    )
    context_benchmark = read_jsonl(
        f"../../data_src/benchmarks/context/{dataset}/bx_{dataset}.jsonl"
    )
    contexts = read_jsonl(
        f"../../data_src/benchmarks/context/{dataset}/contexts_{dataset}.jsonl"
    )
    start(
        dataset,
        rows,
        narrations,
        contexts,
        content_benchmark,
        context_benchmark,
        alphas,
        ns,
        k,
    )

    dataset = "public"
    narrations = read_jsonl(
        f"../../pneuma_summarizer/summaries/narrations/{dataset}.jsonl"
    )
    rows = read_jsonl(f"../../pneuma_summarizer/summaries/rows/{dataset}.jsonl")
    content_benchmark = read_jsonl(
        "../../data_src/benchmarks/content/pneuma_public_bi_questions_annotated.jsonl"
    )
    context_benchmark = read_jsonl(
        f"../../data_src/benchmarks/context/{dataset}/bx_{dataset}.jsonl"
    )
    contexts = read_jsonl(
        f"../../data_src/benchmarks/context/{dataset}/contexts_{dataset}.jsonl"
    )
    start(
        dataset,
        rows,
        narrations,
        contexts,
        content_benchmark,
        context_benchmark,
        alphas,
        ns,
        k,
    )

    dataset = "chembl"
    narrations = read_jsonl(
        f"../../pneuma_summarizer/summaries/narrations/{dataset}.jsonl"
    )
    contexts = read_jsonl(
        f"../../data_src/benchmarks/context/{dataset}/contexts_{dataset}.jsonl"
    )
    rows = read_jsonl(f"../../pneuma_summarizer/summaries/rows/{dataset}.jsonl")
    content_benchmark = read_jsonl(
        "../../data_src/benchmarks/content/pneuma_chembl_10K_questions_annotated.jsonl"
    )
    context_benchmark = read_jsonl(
        f"../../data_src/benchmarks/context/{dataset}/bx_{dataset}.jsonl"
    )
    start(
        dataset,
        rows,
        narrations,
        contexts,
        content_benchmark,
        context_benchmark,
        alphas,
        ns,
        k,
    )

    dataset = "adventure"
    narrations = read_jsonl(
        f"../../pneuma_summarizer/summaries/narrations/{dataset}.jsonl"
    )
    rows = read_jsonl(f"../../pneuma_summarizer/summaries/rows/{dataset}.jsonl")
    content_benchmark = read_jsonl(
        "../../data_src/benchmarks/content/pneuma_adventure_works_questions_annotated.jsonl"
    )
    context_benchmark = read_jsonl(
        f"../../data_src/benchmarks/context/{dataset}/bx_{dataset}.jsonl"
    )
    contexts = read_jsonl(
        f"../../data_src/benchmarks/context/{dataset}/contexts_{dataset}.jsonl"
    )
    start(
        dataset,
        rows,
        narrations,
        contexts,
        content_benchmark,
        context_benchmark,
        alphas,
        ns,
        k,
    )
