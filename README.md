# The Pneuma Project

Pneuma is a data discovery system for tabular data. It consists of multiple components that can be utilized separately.

## Pneuma-Summarizer

This component, which corresponds to the `pneuma_summarizer` directory, produces content summaries to be indexed by retrievers such as `Pneuma-Retriever`.

## Pneuma-Retriever

This component, which corresponds to the `pneuma_retriever` directory, indexes content and context summaries. Then, given a question, it produces a ranking of summaries.

## Pneuma

Our implementation of Pneuma, which combines the previous two components, is available in the `pneuma` directory.

## Benchmark Generators

The benchmark generators are available in the `benchmark_generator` directory. You may download the generated benchmarks in the `data_src` directory, which also provides a way to download the datasets.
