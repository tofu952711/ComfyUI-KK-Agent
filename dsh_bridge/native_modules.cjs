// The bundled exe misses native modules under non-C Windows snapshot paths.
// Extract the native library and its sibling DLLs using the mounted virtual FS.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const dlopen = process.dlopen;

process.dlopen = function (module, filename, ...flags) {
  const source = filename.replace(/^\\\\\?\\/, '');
  if (/^[a-z]:[\\/]snapshot[\\/]/i.test(source)) {
    const content = fs.readFileSync(source);
    const hash = crypto.createHash('sha256').update(content).digest('hex');
    const directory = path.join(process.env.PKG_NATIVE_CACHE_PATH, 'native', hash);
    fs.mkdirSync(directory, { recursive: true });
    for (const name of fs.readdirSync(path.dirname(source))) {
      if (!/\.(dll|node)$/i.test(name)) continue;
      const target = path.join(directory, name);
      if (!fs.existsSync(target)) fs.writeFileSync(target, fs.readFileSync(path.join(path.dirname(source), name)));
    }
    filename = path.join(directory, path.basename(source));
  }
  return dlopen.call(this, module, filename, ...flags);
};
