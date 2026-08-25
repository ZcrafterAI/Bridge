import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import {
  findZosmfProfile,
  loadTeamConfig,
  lookupSecureFromVault,
  mergeConfigs,
  resolveZosmfProperties,
} from "./resolver";

describe("findZosmfProfile", () => {
  it("returns the named profile", () => {
    const config = {
      profiles: { zosmf1: { properties: { host: "zosmf.example.com" } } },
      defaults: { zosmf: "zosmf1" },
    };
    expect(findZosmfProfile(config, "zosmf1")).toEqual({
      properties: { host: "zosmf.example.com" },
    });
  });

  it("falls back to the config default profile when none is named", () => {
    const config = {
      profiles: { zosmf1: { properties: { host: "zosmf.example.com" } } },
      defaults: { zosmf: "zosmf1" },
    };
    expect(findZosmfProfile(config, undefined)).toEqual({
      properties: { host: "zosmf.example.com" },
    });
  });

  it("throws when the profile is missing", () => {
    const config = { profiles: {}, defaults: {} };
    expect(() => findZosmfProfile(config, "missing")).toThrow(/not found/);
  });
});

describe("mergeConfigs", () => {
  it("lets project config override global profile properties", () => {
    const global = {
      profiles: {
        zosmf: { properties: { port: 443, host: "global.example.com" } },
      },
      defaults: { zosmf: "zosmf" },
    };
    const project = {
      profiles: {
        zosmf: { properties: { port: 10443 } },
      },
      defaults: {},
    };
    const merged = mergeConfigs(global, project);
    expect(merged.profiles.zosmf.properties).toEqual({
      host: "global.example.com",
      port: 10443,
    });
  });
});

describe("resolveZosmfProperties", () => {
  it("merges default base profile under the zosmf profile", () => {
    const config = {
      profiles: {
        zosmf: { properties: { port: 10443 }, secure: [] as string[] },
        project_base: {
          properties: { host: "zosmf.example.com", rejectUnauthorized: false },
          secure: ["user", "password"],
        },
      },
      defaults: { zosmf: "zosmf", base: "project_base" },
    };
    const resolved = resolveZosmfProperties(config, "zosmf");
    expect(resolved.properties.host).toBe("zosmf.example.com");
    expect(resolved.properties.port).toBe(10443);
    expect(resolved.properties.rejectUnauthorized).toBe(false);
    expect(resolved.secure).toEqual(expect.arrayContaining(["user", "password"]));
  });

  it("includes basePath when present on the profile", () => {
    const config = {
      profiles: {
        zosmf: {
          properties: { host: "gateway.example.com", port: 7554, basePath: "/ibmzosmf/api/v1" },
        },
      },
      defaults: { zosmf: "zosmf" },
    };
    const resolved = resolveZosmfProperties(config, "zosmf");
    expect(resolved.properties.basePath).toBe("/ibmzosmf/api/v1");
  });
});

describe("loadTeamConfig", () => {
  it("overlays project config on global config", () => {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "zowe-cfg-"));
    const globalDir = path.join(tmp, "global");
    const projectDir = path.join(tmp, "project");
    fs.mkdirSync(globalDir);
    fs.mkdirSync(projectDir);
    fs.writeFileSync(
      path.join(globalDir, "zowe.config.json"),
      JSON.stringify({
        profiles: { zosmf: { properties: { host: "global.host", port: 443 } } },
        defaults: { zosmf: "zosmf" },
      }),
    );
    fs.writeFileSync(
      path.join(projectDir, "zowe.config.json"),
      JSON.stringify({
        profiles: { zosmf: { properties: { port: 10443 } } },
        defaults: {},
      }),
    );

    const config = loadTeamConfig({ globalDir, projectDir });
    expect(config.profiles.zosmf.properties).toEqual({
      host: "global.host",
      port: 10443,
    });
  });
});

describe("lookupSecureFromVault", () => {
  it("reads Zowe v3 secure_config_props keys for a profile field", () => {
    const vault = {
      "C:\\proj\\zowe.config.json": {
        "profiles.project_base.properties.user": "IBMUSER",
        "profiles.project_base.properties.password": "secret",
      },
    };
    expect(
      lookupSecureFromVault(vault, ["C:\\proj\\zowe.config.json"], ["project_base"], "user"),
    ).toBe("IBMUSER");
  });
});
