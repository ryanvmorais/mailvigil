# Releasing

How a MailVigil version reaches PyPI: the one-time setup, then the steps of each release. Publishing
is the maintainer's act; the workflow in [`.github/workflows/release.yml`](../.github/workflows/release.yml)
only does what a GitHub Release tells it to, and PyPI never accepts the same version twice.

## How it works

- Publishing a **GitHub Release** runs the workflow: it builds the sdist and the wheel once, checks
  them, and publishes that exact build to pypi.org.
- **Run workflow** (by hand) does the dry run: the same build, published to test.pypi.org only.
- Both publish with [Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (OIDC): PyPI
  trusts this repository, this workflow and this environment, so no token is stored anywhere.
- The job refuses to publish when the tag is not `v` plus the `version` in `pyproject.toml`.

## One-time setup

1. **pypi.org**: *Your account → Publishing → Add a new pending publisher*, with project name
   `mailvigil`, owner `ryanvmorais`, repository `mailvigil`, workflow `release.yml` and environment
   `pypi`.
2. **test.pypi.org**: the same, with environment `testpypi`.
3. **GitHub** (*Settings → Environments*): create `pypi` with *Required reviewers* (the maintainer)
   and a *Deployment branches and tags* rule for the tag pattern `v*`; create `testpypi` with no
   rule.

A pending publisher creates the project on the first upload and becomes a normal publisher.

## Each release

1. **Version pull request.** In one PR: `version` in `pyproject.toml` and `uv lock`; the
   `[Unreleased]` section of [CHANGELOG.md](../CHANGELOG.md) becomes `[X.Y.Z] - date`, with an empty
   `[Unreleased]` above it and the comparison links; the README says what is true after the release.
   Merge it only with the whole suite green.
2. **Dry run.** *Actions → Release → Run workflow* on `main`. TestPyPI refuses a version it has
   already seen, so this needs the new version. After about a minute, check the install in a clean
   environment:

   ```bash
   uvx --refresh --isolated --default-index https://pypi.org/simple \
     --index https://test.pypi.org/simple/ --index-strategy unsafe-best-match \
     --from mailvigil==X.Y.Z mailvigil --version
   ```

3. **Release.** *Releases → Draft a new release*, *Choose a tag → Create new tag on publish*
   (`vX.Y.Z`, target `main`), no pre-release, release title `MailVigil X.Y.Z` and the body of
   [the template below](#release-notes-template). A draft does nothing: publishing is what starts
   the workflow.
4. **Approve.** The `pypi` job waits for *Review deployments*. This is the point of no return.
5. **Check.** In a clean environment, `uvx --refresh --from mailvigil==X.Y.Z mailvigil --version`
   (the `simple` index can lag a minute behind the upload; repeat before calling it a failure), and
   compare the `sha256` of the wheel on PyPI with the one from the dry run.
6. **Afterwards.** Delete the merged branches, and update the project notes and `CLAUDE.md` with the
   new version.

## A security fix

A vulnerability in a published version does not go through a public issue or pull request: it is
reported privately and the fix is prepared in the advisory's temporary private fork (see
[SECURITY.md](../SECURITY.md)). The release follows the steps above, with four differences:

1. **The merge is made from the advisory page.** The ruleset `proteger-main` blocks it (the fork
   has no CI, so the required checks never report), so for that one merge the bypass of the
   *Repository admin* role is set to always and the box *Merge and bypass branch protections* is
   ticked. Put the bypass back to *pull requests only* right after.
2. **The suite runs on the maintainer's machine** before the merge, since the fork has no CI. The
   version pull request is prepared beforehand and merged right after the fix, so the time the fix
   is public before the tag stays short.
3. **`Patched versions` stays empty** in the advisory until the release is on PyPI; then it is
   filled in and the advisory is published.
4. **The release notes do not mention the advisory while it is a draft.** After it is published,
   the notes get one line, `Security advisory: [GHSA-…](…)`, between the scope line and the last
   line, and the CHANGELOG entry gets the id in parentheses.

## Release notes template

The body of a GitHub Release is short: it says what the version is and where the detail lives, and
the [CHANGELOG](../CHANGELOG.md) keeps the full list. Same shape for every version (the 1.0.0 body
is the model):

- **One opening sentence.** For the first release, what MailVigil is; later, what the version
  brings.
- **Up to five bullets**, one line each, for what a user would notice (a command, an option, a
  guarantee, how to install). No file names, no internal changes.
- **A scope line** that sets expectations in neutral words: the verdict is only as good as the
  reports it receives. No attack steps, payloads, real domains or numbers that work as a recipe.
- **For a security fix, one line with the advisory** between the scope line and the last line, added
  once the advisory is published.
- **The last line links the CHANGELOG section** of the version, with the anchor GitHub makes from
  the heading (`## [1.0.0] - 2026-10-29` becomes `#100---2026-10-29`).

```markdown
<One sentence: what this version is or brings.>

- <What a user notices, one line.>
- <Up to five bullets.>
- Install: `pipx install mailvigil`, or `uv tool install mailvigil`.

<Scope line.> What is public and stable (commands, exit codes, JSON, configuration) is in
docs/stability.md.

Full list of what is in X.Y.Z: [CHANGELOG](https://github.com/ryanvmorais/mailvigil/blob/main/CHANGELOG.md#anchor)
```

## If something goes wrong

- The workflow fails before the publish job: nothing reached PyPI; fix it and run again (delete the
  tag and the Release first if the tag has to move).
- A bad version is published: *yank* it on PyPI (it stays installable by exact pin but is skipped by
  resolvers) and release a patch. A version number is never reused.
