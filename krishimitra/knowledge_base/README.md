# Knowledge base

This folder is intentionally **empty of source documents**. The repository ships no agricultural texts, because every
document must be one the company is authorised to index.

## What to add (via the Developer console → RAG Documents, or the API)
Official crop-management guides, verified disease/pest references, soil and nutrient guidance, authorised product
labels and leaflets, and public FAQs with documented sources.

## Required metadata for every document
Title, source organisation, source URL (if any), **licence / permission**, and **who authorised indexing**.
These are stored with the document and copied into every chunk so each answer can cite its provenance.

## Rules
- Do not upload documents you do not have the right to use.
- Scanned PDFs without a text layer are rejected (OCR them first).
- Treat all documents as untrusted: the assistant is instructed to ignore any instructions found inside them.
- Product-label documents should be linked to `product_labels` (verified flag, crops, targets, restrictions) before the
  recommendation engine will ever mark that product as a supported option.
