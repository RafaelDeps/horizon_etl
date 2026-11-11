# Contract: `normalize_doi(value) -> Optional[str]`

Module: `src/core/logic/horizon_identity.py`. Pure function, no I/O.

## Behaviour

Returns the cleaned DOI of `value`, or `None` when `value` holds no DOI.

Steps, in this order:

1. `None` or blank text -> `None`.
2. When the text has a `doi=` link parameter, keep only its percent-decoded
   value.
3. Lower case.
4. Remove a leading `http://` or `https://` + optional `dx.` + `doi.org/`,
   or a leading `doi:` label.
5. Remove every whitespace character.
6. Remove trailing `.`, `,` and `;`.
7. Return the result when it matches
   `^10\.\d{4,9}(\.\d+)*/\S+$`; otherwise `None`.

The function is idempotent: `normalize_doi(normalize_doi(x)) == normalize_doi(x)`
for every `x` that gives a DOI.

## Examples (each row is a test case)

| Input | Output |
|-------|--------|
| `None` | `None` |
| `""`, `"   "` | `None` |
| `10.1016/j.theriogenology.2018.10.032` | `10.1016/j.theriogenology.2018.10.032` |
| `http://dx.doi.org/10.1016/J.Theriogenology.2018.10.032` | `10.1016/j.theriogenology.2018.10.032` |
| `" https://doi.org/10.1016/j.theriogenology.2018.10.032 "` | `10.1016/j.theriogenology.2018.10.032` |
| `doi:10.1590/S0101-20612006000400005` | `10.1590/s0101-20612006000400005` |
| `http://dx.doi.org/10.1590/S0101-20612006000400005.` | `10.1590/s0101-20612006000400005` |
| `http://dx.doi.org/10.3390 / fishes6030031` | `10.3390/fishes6030031` |
| `http://dx.doi.org/10.5897 /AJAR 2022.16224` | `10.5897/ajar2022.16224` |
| `http://www.scopus.com/scopus/inward/citedby.url?partnerID=x&rel=R6.0.0&doi=10.1186/1753-6561-8-s4-p29&md5=abc` | `10.1186/1753-6561-8-s4-p29` |
| `http://www.scopus.com/…?partnerID=x&doi=10.1186%2F1753-6561-8-s4-p29&md5=abc` | `10.1186/1753-6561-8-s4-p29` |
| `http://www.scopus.com/scopus/inward/citedby.url?partnerID=x&rel=R6.0.0&doi=null&md5=f8a2` | `None` |
| `http://www.scopus.com/…?doi=&md5=f8a2` | `None` |
| `http://www.scopus.com/…?doi=latin american journal of solids&md5=f8a2` | `None` |
| `http://dx.doi.org/1982-9434` | `None` |
| `1982-9434` | `None` |
| `http://dx.doi.org/10.22410/` | `None` |
| `10.1/x` | `None` |
| `not a doi` | `None` |

## Callers and what they rely on

| Caller | Relies on |
|--------|-----------|
| `_find_article` (`src/flows/lattes/projects.py`) | `None` means "match by title and year"; two values that give the same DOI are the same article |
| `ingest_articles_task` (same file) | The returned value is what is stored in `articles.doi` and tracked; `doi_exact` only when it is not `None` |
| `article_decision` (`horizon_identity.py`) | `article:doi:<value>` only for a real DOI; the content id otherwise |
| `lattes_article_key` (`horizon_identity.py`) | An item with a non-DOI value is keyed by title and year |
| `ReferenceConsolidator` (`src/core/logic/reference_consolidator.py`) | Articles are grouped by DOI only for a real DOI |

## Not part of the contract

- No check that the DOI exists (no network call).
- No title comparison: two items with the same DOI are the same article.
