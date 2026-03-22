import { execSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const packageJsonPath = resolve(process.cwd(), "package.json");
const packageJson = JSON.parse(readFileSync(packageJsonPath, "utf-8"));

function resolveTag() {
  const explicitTag = process.argv[2];
  if (explicitTag) {
    return explicitTag.trim();
  }

  const latestTag = execSync("git describe --tags --abbrev=0", {
    encoding: "utf-8"
  }).trim();

  return latestTag;
}

function normalizeVersion(tag) {
  const version = tag.replace(/^v/, "");
  const semverPattern = /^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/;

  if (!semverPattern.test(version)) {
    throw new Error(`Tag '${tag}' is not a valid semver tag like v0.0.3 or 0.0.3`);
  }

  return version;
}

try {
  const tag = resolveTag();
  const version = normalizeVersion(tag);

  if (packageJson.version === version) {
    console.log(`package.json already at version ${version}`);
    process.exit(0);
  }

  packageJson.version = version;
  writeFileSync(packageJsonPath, `${JSON.stringify(packageJson, null, 2)}\n`, "utf-8");

  console.log(`Updated package.json version to ${version} from tag ${tag}`);
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
}
