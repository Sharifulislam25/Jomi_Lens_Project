# Provenance note

At the start of the "Dhaka-only / top-3" work the working folder already contained **uncommitted edits that were not made in that session**:
`src/vdb.py` (schema v2: pending_cases, khas_acquisition, registry_coverage, ledger, issuer_keys, signed documents), `src/verification_engine.py`
(survey-chain, registration-vs-mutation, pending-case, khas/acquisition and document-authenticity checks) and an untracked `src/registry_crypto.py`.
The assistant overwrote `registry_crypto.py` (its original content was never in Git and cannot be recovered) and patched the engine before noticing.
The two recoverable files are preserved here for reference. The project adopted the found schema and checks as its base and re-implemented
`registry_crypto.py` to the interface the found code expects (`verify_chain`, `verify_signature`).
