import path from "node:path";

export const REPO_ROOT = process.cwd();

export const CONFIGS_DIR = path.join(REPO_ROOT, "configs");
export const DATA_DIR = path.join(REPO_ROOT, "data");
export const DOCS_DIR = path.join(REPO_ROOT, "docs");
export const IMG_DIR = path.join(REPO_ROOT, "img");

export const PROMPTS_DIR = path.join(CONFIGS_DIR, "prompts");

export const RAW_DATA_DIR = path.join(DATA_DIR, "raw");
export const INTERMEDIATE_DATA_DIR = path.join(DATA_DIR, "intermediate");
export const PROCESSED_DATA_DIR = path.join(DATA_DIR, "processed");
