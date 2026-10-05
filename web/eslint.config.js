// ESLint recommended + typescript-eslint recommended + react-hooks (coding-style.md rule 1).
import { Module, createRequire } from "node:module";
import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";

// typescript-eslint parses with the TypeScript compiler API, which TypeScript 7 (the app's compiler)
// doesn't ship yet. Until typescript-eslint supports 7, its require("typescript") gets TypeScript 6's
// API from tools/typescript6; tsc itself stays 7.0.2. Remove this with a typescript-eslint that
// supports TypeScript 7.
const require = createRequire(import.meta.url);
const typescriptPath = require.resolve("typescript");
const typescript6 = new Module(typescriptPath);
typescript6.filename = typescriptPath;
typescript6.exports = require("formapp-typescript6");
typescript6.loaded = true;
require.cache[typescriptPath] = typescript6;
const { default: tseslint } = await import("typescript-eslint");

// security.md rule 21: never dangerouslySetInnerHTML.
const noInnerHtml = [
  {
    selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
    message: "Never use dangerouslySetInnerHTML (security.md rule 21).",
  },
  {
    selector: "Property[key.name='dangerouslySetInnerHTML']",
    message: "Never use dangerouslySetInnerHTML (security.md rule 21).",
  },
];
// coding-style.md rule 15: only the client module in src/api/ calls fetch.
const fetchMessage =
  "Call the api through src/api/ (coding-style.md rule 15), not fetch.";
const noFetch = [
  {
    selector: "MemberExpression[property.name='fetch']",
    message: fetchMessage,
  },
];

export default tseslint.config(
  {
    ignores: ["dist", "coverage", "playwright-report", "test-results", "tools"],
  },
  js.configs.recommended,
  tseslint.configs.recommended,
  reactHooks.configs.flat.recommended,
  {
    languageOptions: {
      ecmaVersion: 2022,
      globals: { ...globals.browser },
    },
  },
  {
    files: ["src/**"],
    rules: {
      "no-restricted-globals": [
        "error",
        { name: "fetch", message: fetchMessage },
      ],
      "no-restricted-syntax": ["error", ...noInnerHtml, ...noFetch],
    },
  },
  {
    files: ["src/api/**"],
    rules: {
      "no-restricted-globals": "off",
      "no-restricted-syntax": ["error", ...noInnerHtml],
    },
  },
  {
    files: ["*.config.{js,ts}", "e2e/**"],
    languageOptions: { globals: { ...globals.node } },
  },
);
