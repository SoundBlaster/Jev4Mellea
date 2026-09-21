# Releasing

The release workflow publishes to PyPI when a version tag is pushed. It first
checks that the tagged commit is already reachable from `main` and that the tag
matches the version in `pyproject.toml`. It then runs the compatibility matrix,
builds the source distribution and wheel, and publishes them only after every
previous job succeeds.

## One-time PyPI setup

The project name `mellea-jev-adapter` is not registered on PyPI yet. Before its
first release, configure a pending Trusted Publisher in the PyPI account that
will own the package:

- Publisher: GitHub Actions
- Project name: `mellea-jev-adapter`
- Owner: `SoundBlaster`
- Repository: `Jev4Mellea`
- Workflow filename: `release.yml`
- Environment: `pypi`

PyPI converts the pending publisher to a regular publisher after the first
successful upload. The publishing job uses GitHub OIDC and does not need a
PyPI API token or a stored API key. See [Creating a PyPI project with a Trusted
Publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
and [Publishing with a Trusted Publisher](https://docs.pypi.org/trusted-publishers/using-a-publisher/).

## Release steps

1. Update `project.version` in `pyproject.toml` and merge that change into
   `main`.
2. Create and push the matching version tag from the merged commit, for example:

   ```bash
   git tag v0.1.1
   git push origin v0.1.1
   ```

3. Follow the `Release package` workflow in GitHub Actions. A mismatch, a tag
   outside `main`, a failed compatibility job, or a failed build prevents the
   publish job from running.

The workflow only publishes on `v*` tags. It does not send requests to Jev;
live API checks remain opt-in and billable.

## Preflight without publishing

Before configuring the PyPI Trusted Publisher, the release workflow can be
started manually from the `main` branch in GitHub Actions. This dry run checks
the compatibility matrix, builds both distributions, validates their metadata
and package contents, and installs and imports the wheel. It uploads the
distributions as a workflow artifact but does not publish them to PyPI.
