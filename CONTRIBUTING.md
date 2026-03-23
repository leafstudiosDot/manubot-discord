# Contributing

Thanks for your interest in contributing to Manubot for Discord.

## License agreement
By submitting a pull request, you agree that your contributions are licensed under the Apache License 2.0, the same license as this project.
You confirm that you have the right to submit the code under these terms.

## Attribution
Significant contributions will be credited in the NOTICE file or README at the maintainer's discretion.

## How to contribute
- Open an issue before starting large changes
- Fork the repo and create a branch from `main`
- Follow the existing code style
- Write clear commit messages
- Submit a pull request with a description of what changed and why

## Plugin development

You are welcome to build plugins for Manubot for Discord without being bound by the Apache 2.0 license terms that apply to the core bot.

Plugins that communicate with Manubot for Discord solely through the official Plugin API are not considered derivative works of Manubot for Discord.
You may license your plugin under terms of your choice, including proprietary or commercial terms, if your plugin only uses the public Plugin API and does not copy or modify Manubot core source files.

### What counts as a plugin
- A module that hooks into Manubot for Discord using the Plugin API
- A standalone script that extends bot functionality

### What does not qualify for this exception
- Forks or modifications of the bot core itself
- Code that directly copies or modifies core source files

### Plugin guidelines
- Make clear your plugin is a community plugin, not official
- Use phrasing like "A plugin for Manubot for Discord" in your docs
- Do not imply your plugin is maintained by the original author
- Preserve the NOTICE file attribution if you redistribute any portion of the core bot alongside your plugin

### Publishing your plugin
Consider opening a discussion or issue to get it listed in the community plugin directory in our Discord server.

## Code of conduct
Be respectful. This is a community project.
```

---

**How they work together:**
```
LICENSE      → the legal contract (Apache 2.0)
NOTICE       → your attribution, legally carried by all forks
CONTRIBUTING → what contributors agree to when they submit code