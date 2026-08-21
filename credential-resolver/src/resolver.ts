import * as keytar from "keytar";
import * as fs from "fs";
import * as path from "path";
import * as os from "os";

export interface ZoweProfile {
  properties?: Record<string, unknown>;
  secure?: string[];
  type?: string;
}

export interface ZoweConfig {
  profiles: Record<string, ZoweProfile>;
  defaults?: Record<string, string>;
}

export interface TeamConfigOptions {
  projectDir?: string;
  globalDir?: string;
}

export interface ResolvedZosmfProperties {
  name: string;
  properties: Record<string, unknown>;
  secure: string[];
  lookupProfiles: string[];
  configPaths: string[];
}

export function loadZoweConfig(configPath: string): ZoweConfig {
  if (!fs.existsSync(configPath)) {
    throw new Error(`Zowe config not found at ${configPath}`);
  }
  return JSON.parse(fs.readFileSync(configPath, "utf-8"));
}

function emptyConfig(): ZoweConfig {
  return { profiles: {}, defaults: {} };
}

function readConfigIfExists(configPath: string): ZoweConfig | undefined {
  if (!fs.existsSync(configPath)) {
    return undefined;
  }
  return JSON.parse(fs.readFileSync(configPath, "utf-8"));
}

export function mergeConfigs(lower: ZoweConfig, higher: ZoweConfig): ZoweConfig {
  const profiles: Record<string, ZoweProfile> = {};
  for (const name of new Set([
    ...Object.keys(lower.profiles ?? {}),
    ...Object.keys(higher.profiles ?? {}),
  ])) {
    const fromLower = lower.profiles?.[name] ?? {};
    const fromHigher = higher.profiles?.[name] ?? {};
    profiles[name] = {
      type: fromHigher.type ?? fromLower.type,
      properties: { ...(fromLower.properties ?? {}), ...(fromHigher.properties ?? {}) },
      secure: [...new Set([...(fromLower.secure ?? []), ...(fromHigher.secure ?? [])])],
    };
  }
  return {
    profiles,
    defaults: { ...(lower.defaults ?? {}), ...(higher.defaults ?? {}) },
  };
}

function findProjectConfigDir(startDir: string): string | undefined {
  let dir = path.resolve(startDir);
  while (true) {
    if (
      fs.existsSync(path.join(dir, "zowe.config.json")) ||
      fs.existsSync(path.join(dir, "zowe.config.user.json"))
    ) {
      return dir;
    }
    const parent = path.dirname(dir);
    if (parent === dir) {
      return undefined;
    }
    dir = parent;
  }
}

export function loadTeamConfig(options: TeamConfigOptions = {}): ZoweConfig & { configPaths: string[] } {
  const globalDir = options.globalDir ?? path.join(os.homedir(), ".zowe");
  const projectDir = options.projectDir ?? findProjectConfigDir(process.cwd());
  const layers: Array<{ file: string }> = [
    { file: path.join(globalDir, "zowe.config.json") },
    { file: path.join(globalDir, "zowe.config.user.json") },
  ];
  if (projectDir) {
    layers.push({ file: path.join(projectDir, "zowe.config.json") });
    layers.push({ file: path.join(projectDir, "zowe.config.user.json") });
  }

  let merged = emptyConfig();
  const configPaths: string[] = [];
  for (const layer of layers) {
    const loaded = readConfigIfExists(layer.file);
    if (!loaded) {
      continue;
    }
    configPaths.push(layer.file);
    merged = mergeConfigs(merged, loaded);
  }
  if (configPaths.length === 0) {
    throw new Error(`Zowe config not found under ${globalDir} or project directory`);
  }
  return { ...merged, configPaths };
}

export function findZosmfProfile(config: ZoweConfig, profileName: string | undefined) {
  const name = profileName ?? config.defaults?.zosmf;
  const profile = name ? config.profiles?.[name] : undefined;
  if (!name || !profile) {
    throw new Error(`z/OSMF profile "${name}" not found in Zowe config`);
  }
  return profile;
}

export function resolveZosmfProperties(
  config: ZoweConfig & { configPaths?: string[] },
  profileName?: string,
): ResolvedZosmfProperties {
  const name = profileName ?? config.defaults?.zosmf ?? "";
  const zosmf = findZosmfProfile(config, profileName);
  const baseName = config.defaults?.base;
  const base = baseName ? config.profiles?.[baseName] : undefined;
  const properties: Record<string, unknown> = {
    ...(base?.properties ?? {}),
    ...(zosmf.properties ?? {}),
  };
  const secure = [...new Set([...(base?.secure ?? []), ...(zosmf.secure ?? [])])];
  const lookupProfiles = [name, baseName].filter((value): value is string => Boolean(value));
  return {
    name,
    properties,
    secure,
    lookupProfiles,
    configPaths: config.configPaths ?? [],
  };
}

export function parseSecureConfigProps(raw: string): Record<string, Record<string, string>> {
  const decoded = Buffer.from(raw, "base64").toString("utf8");
  const parsed = JSON.parse(decoded) as Record<string, Record<string, string>>;
  return parsed && typeof parsed === "object" ? parsed : {};
}

export function lookupSecureFromVault(
  vault: Record<string, Record<string, string>>,
  configPaths: string[],
  profileNames: string[],
  field: string,
): string | undefined {
  for (const configPath of configPaths) {
    const bucket = vault[configPath];
    if (!bucket) {
      continue;
    }
    for (const profileName of profileNames) {
      const value = bucket[`profiles.${profileName}.properties.${field}`];
      if (typeof value === "string" && value !== "") {
        return value;
      }
    }
  }
  return undefined;
}

async function loadSecureVault(): Promise<Record<string, Record<string, string>>> {
  const raw = await keytar.getPassword("Zowe", "secure_config_props");
  if (!raw) {
    return {};
  }
  try {
    return parseSecureConfigProps(raw);
  } catch {
    try {
      const parsed = JSON.parse(raw) as Record<string, Record<string, string>>;
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
      return {};
    }
  }
}

async function resolveSecureField(
  configPath: string,
  profileName: string,
  fieldName: string,
): Promise<string | undefined> {
  const account = `${configPath}/profiles/${profileName}/properties/${fieldName}`;
  const value = await keytar.getPassword("Zowe-Secure-Credentials", account);
  return value ?? undefined;
}

async function resolveAllSecureFields(
  resolved: ResolvedZosmfProperties,
): Promise<Record<string, unknown>> {
  const properties = { ...resolved.properties };
  const vault = await loadSecureVault();
  for (const field of resolved.secure) {
    if (properties[field] !== undefined && properties[field] !== "") {
      continue;
    }
    const fromVault = lookupSecureFromVault(vault, resolved.configPaths, resolved.lookupProfiles, field);
    if (fromVault !== undefined) {
      properties[field] = fromVault;
      continue;
    }
    let found: string | undefined;
    for (const configPath of resolved.configPaths) {
      for (const profileName of resolved.lookupProfiles) {
        found = await resolveSecureField(configPath, profileName, field);
        if (found !== undefined) {
          break;
        }
      }
      if (found !== undefined) {
        break;
      }
    }
    if (found !== undefined) {
      properties[field] = found;
    }
  }
  return properties;
}

function buildOutput(properties: Record<string, unknown>) {
  const rejectUnauthorized = properties.rejectUnauthorized;
  const output = {
    host: properties.host,
    port: Number(properties.port ?? 443),
    user: (properties.user as string | undefined)?.trim(),
    password: ((properties.password ?? properties.tokenValue) as string | undefined)?.trim(),
    protocol: (properties.protocol as string | undefined) ?? "https",
    rejectUnauthorized: rejectUnauthorized === undefined ? true : Boolean(rejectUnauthorized),
    basePath: (properties.basePath as string | undefined) ?? null,
  };

  if (!output.host || !output.user || !output.password) {
    throw new Error("Resolved profile is missing host/user/password after credential lookup");
  }
  return output;
}

async function main() {
  const profileArg = process.argv[2];
  const config = loadTeamConfig();
  const resolved = resolveZosmfProperties(config, profileArg);
  const properties = await resolveAllSecureFields(resolved);
  process.stdout.write(JSON.stringify(buildOutput(properties)));
}

if (require.main === module) {
  main().catch((err) => {
    process.stderr.write(String(err?.message ?? err));
    process.exit(1);
  });
}
