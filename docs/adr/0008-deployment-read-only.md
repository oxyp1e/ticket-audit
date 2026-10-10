# 8. The deployed system is read-only and holds no OCR key

**Status:** accepted

## Context
The system is public on the internet so reviewers can see it run. It must not cost money, must not invite real documents, and must not leak credentials.

## Decision
- Azure Container Apps, consumption plan, scale to zero, one replica at most, 0.25 vCPU.
- At startup the container audits the preloaded synthetic batches. OCR results come from the saved Azure responses shipped in the image, through the Azure engine with a page budget of zero: the container has no Document Intelligence key and cannot spend pages. A missing response fails the batch closed.
- Access code (signed, HTTP-only cookie, 12 hours); 5 sign-in attempts per 15 minutes per address; strict content security policy; no indexing.
- **No uploads.** Uploads would spend free-tier pages and invite real documents.
- Log Analytics capped at 0.1 GB a day; a $1 budget alert; the Free Trial subscription's spending limit is on.

## How uploads would work in production
Authenticated users only (Entra ID), files to blob storage with a size and page limit, a storage event starts the audit job, uploads deleted after processing, and the OCR key held in a managed identity / Key Vault, never in the image.
