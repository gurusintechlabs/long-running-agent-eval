import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

// UI-5: untrusted content (agent output, commit messages, test names) is always rendered as text.
// Any raw-HTML sink is an error, in src and in tests alike.
const rawHtmlBan = [
  { selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']", message: "UI-5: raw HTML rendering is banned." },
  { selector: "Property[key.name='dangerouslySetInnerHTML']", message: "UI-5: raw HTML rendering is banned." },
  { selector: "MemberExpression[property.name='innerHTML']", message: "UI-5: innerHTML is banned." },
  { selector: "MemberExpression[property.name='outerHTML']", message: "UI-5: outerHTML is banned." },
  { selector: "CallExpression[callee.property.name='insertAdjacentHTML']", message: "UI-5: insertAdjacentHTML is banned." },
  { selector: "CallExpression[callee.property.name='write'][callee.object.name='document']", message: "UI-5: document.write is banned." },
  { selector: "CallExpression[callee.name='eval']", message: "UI-5: eval is banned." },
  { selector: "NewExpression[callee.name='Function']", message: "UI-5: new Function is banned." },
];

export default tseslint.config(
  { ignores: ["dist", "node_modules"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: { globals: { ...globals.browser } },
    plugins: { "react-hooks": reactHooks },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      "no-restricted-syntax": ["error", ...rawHtmlBan],
      "no-restricted-properties": [
        "error",
        { object: "window", property: "eval", message: "UI-5" },
      ],
    },
  },
);
