import js from '@eslint/js'
import reactHooks from 'eslint-plugin-react-hooks'
import globals from 'globals'

export default [
  { ignores: ['dist/**', 'node_modules/**'] },
  js.configs.recommended,
  {
    files: ['src/**/*.{js,jsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: { ...globals.browser },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // menangkap variabel/fungsi yang tidak didefinisikan (mis. typo saat rename).
      // PascalCase dikecualikan: komponen JSX "terpakai" walau tak dirujuk langsung
      // (tanpa plugin react, base rule tidak melihat JSX).
      'no-undef': 'error',
      'no-unused-vars': ['warn', {
        argsIgnorePattern: '^_',
        varsIgnorePattern: '^_|^[A-Z]',
      }],
      // pola setLoading() di awal effect itu sengaja (indikator muat) — jadikan peringatan
      'react-hooks/set-state-in-effect': 'warn',
    },
  },
]
