import { promises as fs } from "node:fs";
import path from "node:path";
import { CONFIGS_DIR } from "@/lib/paths";

export async function loadJsonConfig<T = unknown>(relativePath: string): Promise<T> {
  const fullPath = path.isAbsolute(relativePath)
    ? relativePath
    : path.join(CONFIGS_DIR, relativePath);
  const contents = await fs.readFile(fullPath, "utf-8");
  return JSON.parse(contents) as T;
}

export async function loadTextConfig(relativePath: string): Promise<string> {
  const fullPath = path.isAbsolute(relativePath)
    ? relativePath
    : path.join(CONFIGS_DIR, relativePath);
  return fs.readFile(fullPath, "utf-8");
}

export async function loadPromptTemplate(name: string): Promise<string> {
  return loadTextConfig(path.join("prompts", name));
}
