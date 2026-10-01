# Reproducibility

Status: Draft for owner review · Last updated: 2026-10-01

## 1. What reproducibility means here

Three different promises, with different strength.

| Level | Promise | Achievable |
|---|---|---|
| **Software** | The same commit and the same pinned base image build the same system | Yes, with pinning |
| **Data and analysis** | Stored extractions, imports, and analysis results are preserved and identifiable. Deterministic steps give the same result when rerun on the same inputs. | Yes for stored records and deterministic code; see the limits in §3 |
| **AI output** | The same question gives the same generated answer | **No.** Language models are not deterministic and hosted models change. The promise is instead *auditability*: the exact inputs, model identifier, and output of every interaction are recorded and can be inspected. |

Stating the limits plainly is part of the design.

## 2. Software

- Python version pinned in `pyproject.toml`.
- Python dependencies locked with hashes in `uv.lock`, committed.
- Container base images pinned by digest. System packages come from the pinned base image; they are not individually version-pinned, because distribution repositories remove old package versions and such pins break builds. The digest fixes what is installed; updating it is a deliberate, reviewed change.
- Builds run in CI from a clean checkout. A developer's machine is never the build source for a release.
- Each release image is tagged with its git commit.
- **Settings that affect results live in the repository**, not in environment variables: model identifiers, generation settings, chunking configurations, retrieval parameters, prompt versions, attempt limits, the prohibited-wording lists.
- Environment variables hold only secrets and deployment-specific addresses.

## 3. Documents

- Raw bytes are stored unmodified and addressed by SHA-256.
- Each acquisition records how the bytes were obtained. For a fetch, the system records what it observed. For an upload, it records the origin the uploader claims and marks it as attested, not verified, unless a later system fetch from that origin yields the same hash.
- A corpus manifest can be exported: every document version with its hash, source, acquisition details, origin verification, and rights status. Someone without access to restricted files can obtain them independently and confirm identity by hash.
- **What extraction guarantees.** Each Extraction is stored with its parser name, version, and configuration, and its Segments are stored permanently. The stored Segments are the reproducible representation: they do not change. Re-running the same parser version on the same artifact is expected to give the same Segments for text-layer formats, but this is not guaranteed for every parser and is not expected for OCR. The project therefore relies on the stored extraction, not on re-derivation.
- A parser upgrade creates a new Extraction and leaves the old one in place.
- **What a Passage guarantees.** A Passage stores its quoted text and hash, so it remains checkable against its stored Segment whatever extraction is later made current. It is not a proof about the artifact bytes: if extraction misread the original, the Passage reproduces the misreading. Checking a Passage against the original means opening the stored artifact and reading it.
- Stored text is in Unicode Normalization Form C with no other transformation ([DATA_MODEL.md](DATA_MODEL.md) §5).

## 4. Indicator data

- Each import is a release with the provider's label, the retrieval time, and the raw file as an artifact.
- Observations are never overwritten. Revisions arrive as new releases.
- Any analysis names the releases it used.
- Values are stored as published, in exact decimals. Derived series are computed in recorded analyses, not stored as source data.

## 5. Policy coding and claims

- Coded values store the codebook version and the passage they were coded from.
- Policy status is computed from recorded formal events, so it can always be recomputed.
- Approved claims are immutable. Revisions supersede.
- Review decisions are recorded with reviewer and time.
- A claim whose evidence becomes unavailable is marked as needing reassessment; its history is kept.
- The audit trail records who changed what.

## 6. Analyses and searches

Each quantitative analysis is recorded as an AnalysisRun:

- Inputs: series and release identifiers, and formal policy events where relevant
- Method and parameters
- Git commit of the code
- Random seed, where randomness is involved
- Result summary and a hash of the full output

Analyses are run by code in the repository, not by hand in a spreadsheet or notebook. Exploratory notebooks are allowed for exploration, and anything that supports a claim is moved into versioned code and recorded as a run.

Each search for sources that supports a claim is recorded as a SearchRun: query, date and time, source universe, inclusion and exclusion criteria, sources examined, method, outcome, and configuration or version metadata where system components were used. A search against live external sites cannot be rerun with a guaranteed identical result, because the sites change. The SearchRun records what was done and found at that time; it is evidence of that, not a repeatable computation.

## 7. Retrieval and embeddings

- RetrievalChunks are derived from Segments under a versioned ChunkingConfiguration held in the repository. Regenerating chunks never alters Segments.
- Embeddings are stored on chunks with the model identifier and version. Vectors from different models are never mixed in one search.
- Retrieval hits are recorded against Segment spans and the chunking configuration version, so the record of what was retrieved survives chunk regeneration.
- Given the same chunks, embeddings, and parameters, lexical retrieval and exact vector search are deterministic, with ties broken by a fixed rule. Approximate vector indexes are not strictly so; if one is introduced, evaluation uses exact search or records the index parameters.
- An open-weights embedding model can be pinned permanently. A hosted embedding model can be withdrawn by its provider, which would force re-embedding and re-evaluation. This is a selection criterion in ADR-0006. Whether an open-weights model can run on the available hardware has not been assessed.

## 8. AI interactions

Recorded for every interaction: question, query analysis, retrieval hits and scores, evidence placed in context, prompt versions, provider, exact model identifiers, generation settings, chunking configuration version, raw output, verification results, final response.

This allows:

- Auditing why an answer said what it said
- Re-running verification on a stored output after the verifier improves
- Re-running synthesis on stored evidence with a new model, as a comparison

It does not allow regenerating an identical answer.

## 9. Evaluation

- Gold datasets are versioned files in the repository. They contain no copyrighted document text.
- The synthetic fixture corpus and the adversarial corpus are committed. The evaluation corpus is identified by a manifest of hashes; the documents are not committed.
- Each evaluation run stores dataset version, corpus manifest identifier, pipeline version, chunking configuration version, prompt versions, model identifiers, and per-case results.
- Reported results always name the run and are broken down by language. A metric without a run identifier is not reported.
- Results apply to the recorded model version only.

## 10. Environment

- All timestamps in UTC.
- Database collation and text search configurations are set explicitly in migrations, not inherited from the host. Adding a language may add such configuration.
- Tests do not depend on wall-clock time, network access, or test ordering.

## 11. Releases of research data

For a publication, a snapshot is produced containing:

- Corpus manifest
- Document texts whose rights permit redistribution
- Policy records with their passages
- Indicator observations with release identifiers, subject to provider licences
- Claims with evidence, including analysis runs and search runs
- Codebook version, protocol version, limitations document
- Git commit of the software

The snapshot is given a version and a checksum. Whether it is deposited in a public archive, and under what licence, is undecided (blocker B7).

## 12. Known gaps

| Gap | Consequence | Mitigation |
|---|---|---|
| Hosted model behaviour changes over time | Answers and evaluation results drift | Record exact model identifiers; rerun evaluation on model change |
| Providers revise or withdraw data | Original source may no longer match | Stored raw release files |
| Source websites change or vanish | Live URL no longer shows the document; a past search cannot be repeated identically | Stored artifacts and hashes; SearchRun records |
| Copyright restricts redistribution | Third parties cannot get all files from us | Manifest with hashes |
| Extraction may not be re-derivable identically, especially with OCR | Re-extraction may differ | Stored Segments are the reference; engine and model versions recorded in the extraction |
| Extraction may misread the original | A Passage can faithfully quote a misreading | Extraction quality recorded; artifact kept for manual checking |
| Uploaded files have attested, not observed, origin | Provenance rests on the uploader's statement | Marked as attested; corroborated when a system fetch matches |
| Redaction removes content | Later checks on that content are impossible | Tombstone, hash, and RedactionRecord kept |
| Human coding involves judgement | Another coder may code differently | Codebook, linked passages, agreement reporting |
