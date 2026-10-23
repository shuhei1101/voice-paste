import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  // 生成した app.js は検査しない（著作は .ts）
  { ignores: ["**/*.js", "node_modules/"] },
  js.configs.recommended,
  ...tseslint.configs.recommendedTypeChecked,
  {
    files: ["src/voice_paste/server/web/**/*.ts"],
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      "@typescript-eslint/no-deprecated": "error",
    },
  },
);
