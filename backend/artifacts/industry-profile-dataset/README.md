# Industry profile dataset

Dataset extracted from the 15 DOCX files under `C:\Users\Administrator\Downloads\DaNganh`.

## Contents

- `industry_profiles.json`: complete structured bundle, including source paragraphs.
- `rag_conversation_cases.jsonl`: 455 synthetic Q&A cases for chatbot evaluation and review.
- `intent_examples.jsonl`: 209 intent records with training utterances.
- `industry_vocabulary.jsonl`: 162 glossary records.
- `catalog_contract.jsonl`: 450 synthetic `DEMO-*` catalog rows and fields to complete.
- `source_boundaries.jsonl`: source-precedence and missing-data rules.
- `industry_qa_seed.vi-en.md`: consolidated Markdown seed for a controlled RAG pilot.
- `rag_conversation_review_template.csv`: review sheet with blank bot-answer and correction columns.
- CSV companions for cases, intents, vocabulary and catalog templates.

## Recommended workflow

1. Use `industry_qa_seed.vi-en.md` as a reviewable seed document for a pilot RAG upload.
2. Use `rag_conversation_cases.jsonl` as the evaluation set. Do not upload this file as general knowledge.
3. For every run, append `bot_answer`, `review_status`, `corrected_answer` and `error_type` in a separate prediction/review file.
4. Keep prices, inventory, orders, appointments and tenant policy in structured Catalog/CRM/Policy sources; the `DEMO-*` rows are synthetic placeholders.
5. Do not treat sample policies as real policies until a shop approves them and adds scope and effective dates.

## Extraction notes

- Source Q&A and catalog examples are synthetic and may contain repeated or mechanically generated phrasing.
- The extractor repairs the character-spaced retrieval guidance found in some DOCX paragraphs.
- The source DOCX paragraphs are retained in `industry_profiles.json` so no content is silently discarded.
