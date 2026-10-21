# Local Lumio + Ariadne example

Start with [the complete local tutorial](../../docs/tutorials/lumio-ariadne-local.md).
It uses released Core 0.6.0 / Lumio 0.4.0, Git and a new local data project.
No S3, Docker, model key, LanceDB or private application is required.

`project/` contains the independently authored three-order fixture and its
curated Metric/Policy/glossary pages. Completed orders 100+50 imply **150 EUR
recognized revenue and two completed orders**; cancelled 25 is excluded.
`demo.py` creates the example, prepares native proposals, previews validation
and admission, and checks the actual CLI answer. It prints human source-approval
and confirmation commands; it never executes either decision.

Never use the helper to reset a real project: creation refuses existing paths.
It sets Git identity only in the disposable tutorial repository. The generated
DuckDB file and `.demo-state.json` are ignored; raw private sources are not
committed. Source permission, validation and release activation remain native.

The tutorial includes a Policy edit: the new local Git HEAD does not change
admitted serving until a new exact overall confirmation. The example's Core
catalog pages are technical pointers required by native graph validation;
the complete curated rule has one maintained source under `knowledge/`.
