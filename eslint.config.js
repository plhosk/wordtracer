import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';
import css from '@eslint/css';
import { defineConfig, globalIgnores } from 'eslint/config';

export default defineConfig([
  globalIgnores(['dist/**', 'android/**']),
  {
    files: ['**/*.{js,mjs,cjs,ts,mts,cts}'],
    plugins: { js },
    extends: ['js/recommended'],
    languageOptions: { globals: globals.browser },
  },
  // Server-specific config (node globals instead of browser)
  {
    files: ['src/server.ts', 'src/persistence.ts'],
    languageOptions: { globals: globals.node },
  },
  tseslint.configs.recommended,
  {
    files: ['**/*.{js,mjs,cjs,ts,mts,cts}'],
    rules: {
      indent: ['error', 2, { SwitchCase: 1 }],
      semi: ['error', 'always'],
      quotes: ['error', 'single', { avoidEscape: true }],
      'array-bracket-spacing': ['error', 'never'],
      'arrow-spacing': 'error',
      'block-spacing': ['error', 'always'],
      'brace-style': ['error', '1tbs', { allowSingleLine: true }],
      'comma-spacing': ['error', { before: false, after: true }],
      'eol-last': ['error', 'always'],
      'keyword-spacing': ['error', { before: true, after: true }],
      'no-mixed-spaces-and-tabs': 'error',
      'no-multi-spaces': 'error',
      'no-multiple-empty-lines': ['error', { max: 1, maxBOF: 0, maxEOF: 1 }],
      'object-curly-spacing': ['error', 'always'],
      'space-before-blocks': ['error', 'always'],
      'space-infix-ops': 'error',
      eqeqeq: ['error', 'always', { null: 'ignore' }],
      'no-duplicate-imports': 'error',
      'no-var': 'error',
      'prefer-const': ['error', { destructuring: 'all' }],
    },
  },
  {
    files: ['**/*.{ts,mts,cts}'],
    rules: {
      '@typescript-eslint/consistent-type-definitions': ['error', 'interface'],
      '@typescript-eslint/explicit-function-return-type': ['error', {
        allowExpressions: true,
        allowTypedFunctionExpressions: true,
      }],
      '@typescript-eslint/no-unused-vars': ['error', {
        argsIgnorePattern: '^_',
        varsIgnorePattern: '^_'
      }],
    },
  },
  {
    files: ['**/*.css'],
    plugins: { css },
    language: 'css/css',
    extends: ['css/recommended'],
    rules: {
      'css/no-invalid-properties': ['error', { allowUnknownVariables: true }],
      'css/use-baseline': 'off',
    },
  },
]);
