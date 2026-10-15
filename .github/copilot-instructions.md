# SDK version rule

Every commit must increase the SDK version unless the person making the change explicitly says not to.

Compatible change: last number + 1 (`1.3.1` -> `1.3.2`). Breaking change: middle number + 1 and last number = 0 (`1.3.2` -> `1.4.0`).

Java version file: `liveavatar-channel-sdk/pom.xml`. Python version file: `pyproject.toml`.

Show the old and new version and wait for agreement before committing. Skip only when explicitly requested, by putting this line in the commit message: `SDK-Version-Bump: skip`.

When the version increases, update `CHANGELOG.md` and `CHANGELOG.zh-CN.md` with `## [x.y.z] - YYYY-MM-DD`. Cover every caller-visible change since the previous version. One or two changes may use category bullets. More than two must be numbered `1.` `2.` `3.` For a new or changed parameter, name the method first, then the parameter, then every allowed value and its effect. Do not start with the event name or JSON field. Put README usage in the existing API section, not at the top. Do not add a README line for every field. Every public method needs a commented call example in the SDK example file, and that example must not run in the normal demo flow.

The full rule is `AGENTS.md`. The local hook is installed with `git config core.hooksPath .githooks`.
