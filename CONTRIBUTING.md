# Contributing

Thanks for your interest in contributing to Manubot for Discord.

## License

Manubot for Discord is licensed under the Apache License 2.0 (see `LICENSE`).
By submitting a pull request you agree that your contribution is licensed under
the Apache License 2.0, and you confirm that you have the right to submit it.

No separate contributor license agreement (CLA) is required.

## Attribution

Significant contributions may be credited in `NOTICE` or the README at the
maintainer's discretion.

## How to contribute

- Open an issue before starting large changes.
- Fork the repository and create a branch from `dev` for ongoing work.
- Follow the existing code style.
- Write clear commit messages.
- Submit a pull request with a description of what changed and why.

## Security reports

Do not open a public issue for a security vulnerability. Contact the
maintainer privately or use the repository security advisory feature instead.

Never include bot tokens, session tokens, passwords, raw direct messages, or
uploaded file contents in issues, pull requests, logs, or test fixtures.

## Plugin development

Plugins that communicate with Manubot for Discord only through a documented
public API, and that do not copy or modify core source files, are generally
separate works rather than derivative works of the core bot. Their authors may
choose their own license subject to applicable law.

This is project policy, not legal advice, and cannot override the Apache
License 2.0 or the copyright interests of third parties. If you plan to
distribute a plugin commercially, or you are unsure whether your plugin is a
derivative work, consult a qualified lawyer.

### What generally counts as a plugin

- A module that integrates through a documented public API
- A standalone script that extends bot functionality without modifying core files

### What does not qualify

- Forks or modifications of the bot core itself
- Code that copies or modifies core source files

### Plugin guidelines

- Make clear that your plugin is a community plugin, not official.
- Use phrasing like "A plugin for Manubot for Discord" in your documentation.
- Do not imply your plugin is maintained by the original author.
- Preserve the `NOTICE` file attribution if you redistribute any portion of
  the core bot alongside your plugin.

## Code of conduct

Be respectful. This is a community project.
