import { defineConfig, type Plugin } from 'vite';

function jsonMinify(): Plugin {
  return {
    name: 'json-minify',
    apply: 'build',
    enforce: 'post',
    generateBundle(_, bundle) {
      for (const [fileName, file] of Object.entries(bundle)) {
        if (fileName.endsWith('.json') && file.type === 'asset') {
          const source = typeof file.source === 'string'
            ? file.source
            : new TextDecoder('utf-8').decode(file.source);
          try {
            const parsed = JSON.parse(source);
            file.source = JSON.stringify(parsed);
          } catch {
            // Not valid JSON, skip
          }
        }
      }
    },
  };
}

export default defineConfig({
  plugins: [jsonMinify()],
  build: {
    chunkSizeWarningLimit: 2000,
  },
});
