# Elk

Zero-codegen Python package management for [Buck2](https://buck2.build). Lock
files (uv or poetry) are read directly by Starlark, and targets are generated
from that.

Much like [`reindeer`](https://github.com/facebookincubator/reindeer), but
for Python.

## Status: experimental

Not seriously tested on a big python codebase, but it does toy examples. It
will probably break if there is more than one version of a particular
dependency.

## Setup:

If you don't have buck going at all, in a new repo: `buck2 init .`.

Add elk as a git-based external cell in your `.buckconfig`:

```ini
[cells]
  root = .
  elk = elk
  prelude = prelude
  ...

[external_cells]
  prelude = bundled
  elk = git

[external_cell_elk]
  git_origin = https://github.com/cormacrelf/elk
  commit_hash = <sha1>
```

The `commit_hash` must be a full SHA-1 (not a branch name). Pin it to a
specific commit.

If your `.buckconfig` has a `[parser] target_platform_detector_spec`, add an
entry for the elk cell:

```ini
[parser]
  target_platform_detector_spec = target:root//...->prelude//platforms:default \
    target:elk//...->prelude//platforms:default \
    target:prelude//...->prelude//platforms:default \
    target:toolchains//...->prelude//platforms:default
```

## Quick start (uv)

From scratch: `uv init`. You may have to be careful about uv overwriting your
.gitignore file, make sure buck-out is still in there afterwards. Then:

1. Your `pyproject.toml` should have a project name and dependencies:

   ```toml
   [project]
   name = "root-package-name"
   version = "0.1.0"
   requires-python = ">=3.12"
   dependencies = [
     "numpy>=2.0",
     "cowsay>=6.1",
   ]
   ```

2. Lock your dependencies and create the symlink Buck2 needs to load TOML:

       uv lock
       ln -s uv.lock uv.lock.toml

3. Generate a platform tags file (once per target platform):

       buck2 run elk//tools:save_tags -- linux-x86_64.tags.json

4. Write a BUCK file that loads everything directly:

   ```python
   load("@elk//:elk.bzl", "elk_packages", "uv_deps", "uv_packages")
   load(":linux-x86_64.tags.json", linux_x86_64_tags = "value")
   load(":uv.lock.toml", lock = "value")

   elk_packages(
       packages = uv_packages(lock),
       platform_tags = {
           "linux-x86_64": linux_x86_64_tags,
       },
   )

   python_binary(
       name = "main",
       main = "main.py",
       # automatically read deps of the root package from uv.lock
       deps = uv_deps(lock, "root-package-name"),
   )
   ```

5. Build and run:

       buck2 run :main

### Adding dependencies

    uv add requests
    buck2 run :main

No regeneration step needed. Buck2 reads the updated lock file automatically.

## Quick start (poetry)

1. Lock your dependencies and create the symlink Buck2 needs to load TOML:

       poetry lock
       ln -s poetry.lock poetry.lock.toml

2. Generate a platform tags file (once per target platform):

       buck2 run elk//tools:save_tags -- linux-x86_64.tags.json

3. Write a BUCK file that loads everything.

   ```python
   load("@elk//:elk.bzl", "elk_packages", "poetry_packages")
   load(":linux-x86_64.tags.json", linux_x86_64_tags = "value")
   load(":poetry.lock.toml", lock = "value")

   elk_packages(
       packages = poetry_packages(lock),
       platform_tags = {
           "linux-x86_64": linux_x86_64_tags,
       },
   )
   ```

4. Build and run:

       buck2 run :main

### Adding dependencies

    poetry add requests
    poetry lock
    buck2 build //:requests

No regeneration step needed. Buck2 reads the updated lock file directly.

## Replacing a package

`overrides` maps a package's target name to a label, and that package's
alias points at the label instead of the `prebuilt_python_library` elk
would generate. Other packages that depend on it get the replacement.

```python
elk_packages(
    packages = uv_packages(lock),
    platform_tags = {"linux-x86_64": linux_x86_64_tags},
    overrides = {
        "claude-agent-sdk": ":claude-agent-sdk-without-cli",
    },
)

# elk still declares the wheel's download, named after the wheel file, so
# the replacement starts from the version and hash the lock pins.
genrule(
    name = "claude-agent-sdk-without-cli.whl",
    srcs = [":claude_agent_sdk-0.2.82-py3-none-manylinux_2_17_x86_64.whl"],
    out = "claude_agent_sdk-0.2.82-py3-none-manylinux_2_17_x86_64.whl",
    cmd = "$(exe :strip_bundled_cli) $SRCS $OUT",
)

prebuilt_python_library(
    name = "claude-agent-sdk-without-cli",
    binary_src = ":claude-agent-sdk-without-cli.whl",
    deps = uv_deps(lock, "claude-agent-sdk"),
)
```

Keys are the names elk gives the alias: normalised, and `{name}-{version}`
when the lock holds several versions of a package. A key that names no
package is an error. A package with no wheel for any configured platform
(an sdist-only package, say) can be supplied this way too.

`example/overrides` replaces one package from source and one by passing its
pinned wheel through a genrule.

### Wheels that load native libraries

A manylinux wheel's extension modules name `libstdc++.so.6`,
`libgcc_s.so.1` or `libz.so.1` as needed libraries and expect them from the
host. Where the host has none at those paths (NixOS, a nix-only container
image), importing the module fails. Give the Python toolchain the libraries
instead of patching each wheel: `PythonToolchainInfo.preload_deps` puts them
in every binary's and test's native-libs directory, on `LD_LIBRARY_PATH` and
`LD_PRELOAD`, so the wheel loads them unchanged and the libraries are buck
dependencies. An override is for a fix that has to change the wheel itself,
such as dropping a bundled executable built for another loader. A per-wheel
patchelf step is tracked in
[elk#6](https://github.com/cormacrelf/elk/issues/6).

## Packaging tags

Python packaging relies on huge lists of tags with which to match a platform
and any compiled wheels that may be appropriate. On a given platform, the first
wheel found in tag order is the one that gets installed, so a list of tags is a
list of preferences for wheels really. Python binaries normally have their deps
downloaded where they'll be run, so `packaging` can list out the platform's
tags in situ, and download the correct wheels. When building with buck, you are
basically going to build a PEX or whatever with bundled binary wheels, for a
target platform that is not necessarily the same as the host. Basically: Buck
needs to know platform tags in advance.

We need to know which wheels to bundle, and that depends on the
target platform and the tags enumerated by `packaging` on that platform. It is
generally impossible to know what tags will be available without basically
running the `packaging` package on that platform.

Elk ships a `save_tags` tool as a `python_binary` that generates platform
tags JSON files using the `packaging` library:

    buck2 run elk//tools:save_tags -- linux-x86_64.tags.json
    buck2 run elk//tools:save_tags -- -   # stdout

Please note this will run against `toolchains//:python` on your host platform.
That is all you need if your host and target platforms are the same, but if
they differ you will have to actually run this on your target platform somehow.

If it's not convenient to do all this with buck, you can just run a one-liner
on your target platform directly. You will need the `packaging` package
installed somehow (e.g. `uv run --with packaging python3 -c ...`).


```sh
python3 -c "import json; from packaging.tags import sys_tags; json.dump([str(t) for t in sys_tags()], open('linux-x86_64.tags.json','w+'), indent=4)"
```

## Development

Requires [Nix](https://nixos.org):

    nix develop

This gives you `buck2`, `uv`, etc.

See `example/` for working uv and poetry setups.
