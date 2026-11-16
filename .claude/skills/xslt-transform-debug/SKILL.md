---
name: xslt-transform-debug
description: Diagnose and fix a failing XML/XSLT transform or schema validation in this repo. Use when a migration record fails, a transform produces wrong or empty output, or a customer sends XML that won't validate.
---

# Debug an XSLT transform or XSD validation failure

Repeatable procedure for the most common implementation defect in this kit:
content goes in, and the wrong thing (or nothing) comes out.

## 1. Reproduce with the smallest input
- Copy the failing record into `/tmp/repro.xml`. For a migration failure, take the single `<doc>` named by
  `legacy_id` in the migration report, not the whole export.
- Confirm it is well-formed first:
  `python -c "from app import xml_pipeline as x; x.read(__import__('pathlib').Path('/tmp/repro.xml'))"`
  A syntax error here means the source system sent broken XML. Stop and report it upstream; don't patch the transform.

## 2. Run the transform on its own and look at the raw output
```python
from pathlib import Path
from app import xml_pipeline as x
doc = x.read(Path("/tmp/repro.xml"))
out = x.transform(doc, "legacy_to_article.xsl")   # or the stylesheet in question
print(str(out))
print(x.validate(out))
```

## 3. Match the symptom to the usual cause
| Symptom | Usual cause | Fix |
|---|---|---|
| Output is empty | No template matched the root: wrong element name, or a namespace the stylesheet doesn't declare | Declare the source namespace with a prefix and use it in `match`/`select` |
| Wrong template fires | Two templates match with equal priority; the processor takes the last one | Add an explicit `priority="1"` (this bit `article_to_feed.xsl` once) |
| Field missing in output | XPath is relative to the wrong context node | Check what `.` is inside `for-each`/`apply-templates` |
| Date or enum fails XSD | Source format differs from what the transform assumes (e.g. `d/m/yyyy`) | Guard with `string-length()` and handle each variant; add a test case |
| Text has odd whitespace | Source has indentation inside elements | Wrap with `normalize-space()` |
| Schema error says `line N` | Line in the transformed output, not the source | Print the output (step 2) and read that line |

## 4. Fix at the root, then lock it in
- Change the stylesheet, not the data, unless the data is genuinely wrong. If it is, record that in the migration report notes.
- Add the minimal repro as a test case in `tests/test_xml_pipeline.py` or `tests/test_migration.py`.
- Run `pytest -q`, then `python scripts/migrate.py <export> --dry-run`, and confirm `reconciled: true`
  and that the failure count dropped by exactly the records you expected.

## 5. Write it down
Add a row to the "Known issues" table in `docs/RUNBOOK.md`: symptom, cause, fix.
The next person shouldn't have to rediscover it.
