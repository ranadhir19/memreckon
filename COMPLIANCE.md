# IP / legal compliance record — memreckon

Written before publication, per the standing compliance gate. Every
claim below was checked against the tree that will be pushed.

## Original name

`memreckon` was coined for this project. The collision check (GitHub,
PyPI, web products) is recorded in [NAME_CHECK.md](NAME_CHECK.md): the
two nearest candidates (memattest, memseal) were found occupied and
rejected; `memreckon` itself returned no product, package, or repository
of that name.

## Original code and copy

- All code and documentation in this repository were written for this
  project on 2026-11-20. No code was copied from any other project.
- The seed for the *idea* was a social-media reel showcasing a shared
  agent-memory tool. Per the reference rule, only the idea — portable,
  cross-agent memory — was taken. No name, copy, structure, or
  implementation of the referenced tool (or of any landscape entrant)
  appears here; memreckon does not store memory at all, which is the
  opposite end of the stack from the seed.
- The `memoryvault` adapter implements the *documented file formats* of
  memoryvault-agents (MemoryDoc frontmatter and the JSON state export)
  for interoperability. No memoryvault-agents code is copied or derived;
  format-level interoperability with an MIT-licensed sibling project by
  the same author is the intent, and the adapter is original code.
- The landscape findings cited in the README (the verification column
  scoring zero across twelve systems) come from a same-author research
  analysis written for this portfolio; the summary here is original
  prose, not a reproduction of any third-party text.

## License

This project is MIT-licensed; the full text is in [LICENSE](LICENSE).

## Third-party dependencies

None. memreckon runs on the Python standard library alone
(`requires-python >= 3.10`; `tomllib` is used where available, with a
regex fallback path for line-oriented formats). There is nothing to
vendor and no third-party license to comply with beyond the standard
library's own. Tools memreckon *invokes* against an audited repository
(git, the repository's own test runner) are the operator's installed
software, not dependencies of this project, and are never redistributed.

## Asset provenance

No third-party assets: no images, fonts, data files, or model weights.
The test fixture (fixtures/build_fixture.py) is original content
written for this repository, including its deliberately failing test,
which is labelled as such in its own source.

## Secrets scan

`validate.py` stage 6 scans the exact publication tree for common
secret shapes (cloud keys, private-key blocks, platform tokens). Result
at build time: **clean** (see the validate.py run in the build log).
No credentials, tokens, or personal data appear anywhere in the tree;
the fixture uses a single synthetic source id (`session:fixture`).
