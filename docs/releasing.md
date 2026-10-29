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
   (`vX.Y.Z`, target `main`), no pre-release, notes from the CHANGELOG. A draft does nothing:
   publishing is what starts the workflow.
4. **Approve.** The `pypi` job waits for *Review deployments*. This is the point of no return.
5. **Check.** In a clean environment, `uvx --refresh --from mailvigil==X.Y.Z mailvigil --version`
   (the `simple` index can lag a minute behind the upload; repeat before calling it a failure), and
   compare the `sha256` of the wheel on PyPI with the one from the dry run.
6. **Afterwards.** Delete the merged branches, and update the project notes and `CLAUDE.md` with the
   new version.

## If something goes wrong

- The workflow fails before the publish job: nothing reached PyPI; fix it and run again (delete the
  tag and the Release first if the tag has to move).
- A bad version is published: *yank* it on PyPI (it stays installable by exact pin but is skipped by
  resolvers) and release a patch. A version number is never reused.
